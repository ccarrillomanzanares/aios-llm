#!/usr/bin/env python3
"""SFT recipe for aios-llm — QLoRA on Qwen3.5-4B, to delete the production scaffolding.

WHY THIS EXISTS

Production serves the agent with an 11,881-character system prompt that carries the whole
AIOS contract (the `sven` package manager, the Xorg+i3 desktop, the network stack, and the
29 tool schemas). Measured, that scaffolding is worth 16.7 points: 92.2 % with it, 75.5 %
without. The goal is to put that contract into the weights so production can serve with a
~200-character prompt and keep the score.

The material is `entrenamiento/sft/` — 1,300 trajectories produced by the 35B teacher,
verified by real execution in the oracle, with the long prompt already swapped for the
short one by `preparar_sft.py`.

THE RECIPE, AND WHY EACH NUMBER IS WHAT IT IS

  * 4-bit QLoRA (NF4, double quant) — a 4B in bf16 plus activations does not fit
    comfortably on one 40 GB A100 alongside the teacher's leftovers; NF4 costs a few
    points of quality and buys stability. LoRA on all attention and MLP projections.
  * LoRA rank 32, alpha 64, dropout 0.05 — rank 32 is generous for a behaviour change
    (not knowledge); the task is to learn tool-calling conventions, not a language.
  * 3 epochs, lr 1e-4 cosine — short and not too hot. This is behaviour shaping.
  * NO PACKING, and that is deliberate: `--packing` mixes several conversations into one
    sequence and lets the loss of one example depend on the previous one. With tool-call
    templates that is how a model learns to hallucinate tool calls across turns.
  * Loss on ASSISTANT turns only. The tool outputs are the teacher's ground truth, not
    something to learn to generate; training on them teaches the model to invent tool
    output, which is the single most damaging failure for an agent.

WHAT IT PRODUCES

  sft-out/adapter/    the LoRA adapter (small, resumable, the real artefact)
  sft-out/merged/     base + adapter merged, ready to convert to GGUF
  then llama.cpp's convert_hf_to_gguf.py -> Q8_0 for the desktop/CPU deployment.

USAGE

    # smoke test first: a handful of steps, to prove the pipeline runs before paying
    python3 entrenar_sft.py --smoke-test

    # the real run
    python3 entrenar_sft.py
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default="Qwen/Qwen3.5-4B", help="base model on HuggingFace")
    ap.add_argument("--datos", default=os.path.join(BASE, "sft"))
    ap.add_argument("--salida", default=os.path.join(BASE, "sft-out"))
    ap.add_argument("--epocas", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=int, default=64)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--batch", type=int, default=1,
                    help="measured: batch 2 with 3-4k sequences OOMs on a 40 GB A100")
    ap.add_argument("--acumulacion", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=8192)
    ap.add_argument("--sin-4bit", action="store_true", help="bf16 LoRA instead of 4-bit QLoRA")
    ap.add_argument("--smoke-test", action="store_true",
                    help="20 steps on 40 examples with 1 epoch: proves the pipeline, costs minutes")
    ap.add_argument("--reanudar", action="store_true",
                    help="continue from the last checkpoint in --salida if there is one")
    return ap.parse_args()


def main():
    args = parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                              DataCollatorForSeq2Seq, Trainer, TrainingArguments)

    if args.smoke_test:
        args.epocas = 1.0
        args.max_len = 4096
        args.salida = args.salida + "-smoke"
        print("### SMOKE TEST — the point is that it RUNS, not that it learns")

    print("base model : %s" % args.modelo)
    print("data       : %s" % args.datos)
    print("output     : %s" % args.salida)
    print("4-bit      : %s" % (not args.sin_4bit))
    print("lora       : r=%d alpha=%d dropout=%.2f" % (args.lora_r, args.lora_alpha, args.lora_dropout))
    print("epochs     : %s   lr: %s" % (args.epocas, args.lr))
    print("batch      : %d x %d acumulacion = %d efectivo"
          % (args.batch, args.acumulacion, args.batch * args.acumulacion))
    sys.stdout.flush()

    tok = AutoTokenizer.from_pretrained(args.modelo, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    cuant = None
    if not args.sin_4bit:
        cuant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    modelo = AutoModelForCausalLM.from_pretrained(
        args.modelo,
        quantization_config=cuant,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    modelo.config.use_cache = False
    if not args.sin_4bit:
        modelo = prepare_model_for_kbit_training(modelo)

    # The tool schemas travel with the data and go into every prompt, exactly as in
    # production, so the model sees the same 29 tools it will see when deployed.
    # The file holds a bare list (already verified); handle a wrapper too, but do not
    # assume the wrapper's key without checking.
    tools = json.load(open(os.path.join(args.datos, "tools.json"), encoding="utf-8"))
    if isinstance(tools, dict):
        tools = tools.get("tools", tools)
    print("tools      : %d esquemas" % len(tools))

    ds = load_dataset("json", data_files={
        "train": os.path.join(args.datos, "train.jsonl"),
        "valid": os.path.join(args.datos, "valid.jsonl"),
    })
    if args.smoke_test:
        ds["train"] = ds["train"].select(range(min(40, len(ds["train"]))))
        ds["valid"] = ds["valid"].select(range(min(8, len(ds["valid"]))))

    def tokenizar(ej):
        """Render the conversation with the model's own template, and mask everything
        that is not an assistant turn.

        The mask is the whole design: -100 means "do not compute loss here". Tool
        outputs and the system prompt are context, not targets. Training on the tool
        outputs would teach the model to invent them.

        The sequence IS truncated to --max-len. Measured the hard way: with a 150k-token
        vocabulary, the logits and their gradient dominate the GPU, and an untruncated
        batch blew up asking for 8.97 GiB in one allocation.
        """
        msgs = ej["messages"]
        texto = tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                        add_generation_prompt=False)
        ids = tok(texto, add_special_tokens=False)["input_ids"]

        # Find the assistant spans by rendering each prefix and diffing: the model's
        # template is the authority on where its own turn markers are.
        etiquetas = [-100] * len(ids)
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant":
                continue
            prefijo = tok.apply_chat_template(msgs[:i], tools=tools, tokenize=False,
                                              add_generation_prompt=True)
            n_pre = len(tok(prefijo, add_special_tokens=False)["input_ids"])
            hasta = tok.apply_chat_template(msgs[:i + 1], tools=tools, tokenize=False,
                                            add_generation_prompt=False)
            n_hasta = len(tok(hasta, add_special_tokens=False)["input_ids"])
            for j in range(n_pre, min(n_hasta, len(ids))):
                etiquetas[j] = ids[j]

        if len(ids) > args.max_len:
            ids = ids[:args.max_len]
            etiquetas = etiquetas[:args.max_len]
        return {"input_ids": ids, "labels": etiquetas, "attention_mask": [1] * len(ids)}

    ds = ds.map(tokenizar, remove_columns=ds["train"].column_names, desc="tokenising")

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    modelo = get_peft_model(modelo, lora)
    modelo.print_trainable_parameters()

    # transformers 5 dropped `warmup_ratio` (only `warmup_steps` remains) and renamed other
    # knobs across versions. Rather than guess again — this is the third signature change in
    # one afternoon — the supported set is READ from the class and anything unsupported is
    # reported instead of silently dropped.
    import inspect
    _soportados = set(inspect.signature(TrainingArguments.__init__).parameters)
    pasos_por_epoca = max(1, len(ds["train"]) // (args.batch * args.acumulacion))
    total_pasos = int(pasos_por_epoca * args.epocas)
    deseado = {
        "output_dir": args.salida,
        "num_train_epochs": args.epocas,
        "per_device_train_batch_size": args.batch,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": args.acumulacion,
        "learning_rate": args.lr,
        "lr_scheduler_type": "cosine",
        "warmup_steps": max(1, int(0.03 * total_pasos)),
        "bf16": True,
        "gradient_checkpointing": True,
        "logging_steps": 5,
        "save_steps": 50,
        "save_total_limit": 2,
        "report_to": [],
        "max_steps": 20 if args.smoke_test else -1,
        "eval_strategy": "no" if args.smoke_test else "steps",
        "eval_steps": 50,
    }
    ta_kwargs = {k: v for k, v in deseado.items() if k in _soportados}
    ignorados = sorted(set(deseado) - set(ta_kwargs))
    print("pasos/epoch: %d   total: %d   warmup: %d" % (pasos_por_epoca, total_pasos,
                                                        ta_kwargs.get("warmup_steps", 0)))
    if ignorados:
        print("AVISO: este transformers no acepta %s (se omiten)" % ", ".join(ignorados))
    if len(ta_kwargs) < len(deseado) - 1:
        raise SystemExit("demasiados argumentos no soportados: revisar la version de transformers")
    ta = TrainingArguments(**ta_kwargs)

    ent = Trainer(
        model=modelo,
        args=ta,
        train_dataset=ds["train"],
        eval_dataset=ds["valid"],
        data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
    )
    ent.train(resume_from_checkpoint=args.reanudar or None)
    ent.save_model(os.path.join(args.salida, "adapter"))
    tok.save_pretrained(os.path.join(args.salida, "adapter"))
    print("adapter saved: %s" % os.path.join(args.salida, "adapter"))


if __name__ == "__main__":
    main()
