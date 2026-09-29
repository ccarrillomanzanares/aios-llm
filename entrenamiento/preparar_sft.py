#!/usr/bin/env python3
"""Turn the verified Phase-1 material into an SFT dataset — and say what it dropped.

WHAT THIS IS FOR

The fine-tune's objective is to delete the scaffolding from production: serve the model
with the 214-character prompt instead of the 11,881-character one, and keep the score.
Measured, that scaffolding is worth 16.7 points (92.2 % with it, 75.5 % without).

So the training data must be built BECAUSE OF that objective, not merely from what the
teacher produced. Three consequences, and each one throws material away:

1. THE SYSTEM PROMPT IS REWRITTEN. Every trajectory was generated with the long prompt
   in the system turn. Training on it as-is would teach the model to LEAN ON the
   scaffolding — the exact opposite of the goal. The system turn is replaced by the
   short prompt, so the model learns to produce the same behaviour from far less.

2. NOISY TRAJECTORIES ARE DROPPED. A trajectory can pass the generator's filter and
   still model bad behaviour: the teacher sometimes reaches for `screenshot` on a
   package question, which is precisely the failure the fine-tune has to fix. Training
   on that teaches the bug. A trajectory is dropped when it calls a UI-capture tool the
   case never asked for.

3. EXACT DUPLICATES ARE COLLAPSED. Six temperatures over the same case are there to
   give variety, and they do — but where two temperatures produced the same tool
   sequence and the same closing answer, the pair is one example, not two. Feeding
   duplicates to the trainer weights those cases more than the rest, silently.

WHAT IT DOES NOT DO

It does not touch the reserved cases. The material was generated without them by design
(holdout.txt), so the exam stays honest. This script asserts that, rather than trusting
it: if a reserved case shows up in the material, it stops.

USAGE
    python3 preparar_sft.py                      # writes train/valid, prints the report
    python3 preparar_sft.py --solo-informe       # report only, writes nothing
"""
import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))          # .../aios-llm/entrenamiento
BATERIA = os.path.join(os.path.dirname(BASE), "bateria")   # .../aios-llm/bateria


def leer_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        for n, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield n, json.loads(ln)
            except json.JSONDecodeError as e:
                raise SystemExit("line %d of %s is not valid JSON: %s" % (n, ruta, e))


def leer_reservados():
    """Cases that must NEVER appear in material. Read, not assumed."""
    ruta = os.path.join(BATERIA, "holdout.txt")
    reservados = set()
    if not os.path.exists(ruta):
        return reservados
    for ln in open(ruta, encoding="utf-8"):
        ln = ln.split("#")[0].strip()
        if ln:
            reservados.add(ln)
    return reservados


def herramientas_del_caso(caso, casos):
    """Every tool the case treats as legitimate, from esperado AND alternativas."""
    c = casos.get(caso) or {}
    e = c.get("esperado") or {}
    nombres = {e.get("herramienta")}
    for a in (e.get("alternativas") or []):
        nombres.add(a.get("herramienta"))
    for cl in (e.get("claves") or []):
        pass
    return {n for n in nombres if n}


def firma(d):
    """Identity of a trajectory's BEHAVIOUR, for duplicate collapsing.

    Two runs at different temperatures that used the same tools and closed with the
    same answer are the same example. The temperature is not part of the identity —
    that is the whole point of collapsing them.
    """
    pasos = []
    for m in d["mensajes"]:
        for tc in (m.get("tool_calls") or []):
            f = tc.get("function", {})
            pasos.append(f.get("name", "") + "|" + (f.get("arguments") or ""))
    cierre = ""
    for m in reversed(d["mensajes"]):
        if m.get("role") == "assistant" and not m.get("tool_calls"):
            cierre = (m.get("content") or "").strip()
            break
    h = hashlib.sha256(("\n".join(pasos) + "\n@@\n" + cierre).encode("utf-8"))
    return h.hexdigest()[:16]


def es_ruidosa(d, casos):
    """True if the trajectory calls a UI-capture tool the case never asked for.

    The teacher's known bad habit: on a package question it takes a screenshot instead
    of querying the package manager. Those runs pass the generator's filter (the case's
    tool IS eventually called) but they model the bug this fine-tune exists to remove.
    """
    legitimos = herramientas_del_caso(d["caso"], casos)
    # Tools that only make sense when the case is about the desktop.
    captura = {"screenshot", "ocr"}
    llamadas = set()
    for m in d["mensajes"]:
        for tc in (m.get("tool_calls") or []):
            llamadas.add(tc.get("function", {}).get("name", ""))
    intrusas = (llamadas & captura) - legitimos
    return bool(intrusas), sorted(intrusas)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--material", default=os.path.join(BATERIA, "dataset_fase1-B-lambda.jsonl"))
    ap.add_argument("--casos", default=os.path.join(BATERIA, "casos.json"))
    ap.add_argument("--prompt-corto", default=os.path.join(BATERIA, "prompt_corto.txt"))
    ap.add_argument("--salida", default=os.path.join(BASE, "sft"))
    ap.add_argument("--valid-por-caso", type=int, default=1,
                    help="trajectories per case held for validation (0 = split at random)")
    ap.add_argument("--semilla", type=int, default=20260929)
    ap.add_argument("--solo-informe", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    prompt_corto = open(args.prompt_corto, encoding="utf-8").read().rstrip()
    _cj = json.load(open(args.casos, encoding="utf-8"))
    _lista = _cj["casos"] if isinstance(_cj, dict) else _cj
    casos = {c["id"]: c for c in _lista}
    reservados = leer_reservados()
    print("material   : %s" % args.material)
    print("cases      : %d" % len(casos))
    print("reserved   : %d cases that must not appear in the material" % len(reservados))
    if reservados:
        dentro = [c for c in reservados if c in casos]
        print("             %s" % ", ".join(sorted(dentro)[:12]))

    total = ruidosas = reservadas = 0
    por_clave = defaultdict(list)
    motivos = Counter()
    intrusas_por_caso = Counter()

    for n, d in leer_jsonl(args.material):
        total += 1
        caso = d.get("caso")
        if reservados and caso in reservados:
            reservadas += 1
            motivos["case is reserved (must never train)"] += 1
            continue
        mal, cuáles = es_ruidosa(d, casos)
        if mal:
            ruidosas += 1
            motivos["calls UI-capture tool the case never asked for: " + ",".join(cuáles)] += 1
            for c in cuáles:
                intrusas_por_caso["%s (%s)" % (caso, c)] += 1
            continue
        msgs = []
        for m in d["mensajes"]:
            m = dict(m)
            # `arguments` arrives as a JSON STRING (OpenAI wire format) and the model's own
            # chat template does `tool_call.arguments|items`, which needs a MAPPING —
            # otherwise Jinja raises "Can only get item pairs from a mapping". Measured, and
            # caught by the smoke test in two minutes instead of three hours of training.
            if m.get("tool_calls"):
                tcs = []
                for tc in m["tool_calls"]:
                    tc = dict(tc)
                    f = dict(tc.get("function") or {})
                    a = f.get("arguments")
                    if isinstance(a, str):
                        try:
                            f["arguments"] = json.loads(a) if a.strip() else {}
                        except json.JSONDecodeError:
                            f["arguments"] = {"_raw": a}
                    tc["function"] = f
                    tcs.append(tc)
                m["tool_calls"] = tcs
            msgs.append(m)
        if not msgs or msgs[0].get("role") != "system":
            motivos["no system turn"] += 1
            continue
        msgs[0]["content"] = prompt_corto          # (1) swap the scaffolding out
        ej = {
            "id": "%s-%s-t%s-n%d" % (caso, d.get("idioma"), d.get("temperatura"), n),
            "messages": msgs,
            "caso": caso,
            "grupo": d.get("grupo"),
            "idioma": d.get("idioma"),
            "temperatura": d.get("temperatura"),
            "herramientas": d.get("herramientas"),
        }
        por_clave[firma(d)].append(ej)

    # (3) collapse exact behavioural duplicates
    ejemplos, duplicados = [], 0
    for k, v in por_clave.items():
        ejemplos.append(v[0])
        duplicados += len(v) - 1
    ejemplos.sort(key=lambda e: (e["caso"], e["idioma"] or "", e["id"]))
    motivos["exact behavioural duplicate (same tools AND same closing answer)"] += duplicados

    # split: hold one trajectory per case for validation, so every block is represented
    rnd = random.Random(args.semilla)
    por_caso = defaultdict(list)
    for e in ejemplos:
        por_caso[e["caso"]].append(e)
    train, valid = [], []
    for caso, lista in por_caso.items():
        rnd.shuffle(lista)
        k = min(args.valid_por_caso, max(0, len(lista) - 1))
        valid.extend(lista[:k])
        train.extend(lista[k:])
    train.sort(key=lambda e: e["id"])
    valid.sort(key=lambda e: e["id"])

    print()
    print("=== WHAT CAME IN ===")
    print("  trajectories in the material : %d" % total)
    print("=== WHAT WAS DROPPED, AND WHY ===")
    for motivo, n in motivos.most_common():
        print("  %-70s %5d" % (motivo[:70], n))
    if intrusas_por_caso:
        print("  --- where the UI-capture intrusion happened:")
        for k, v in intrusas_por_caso.most_common(8):
            print("      %-40s %4d" % (k, v))
    print("=== WHAT THE TRAINER GETS ===")
    print("  train : %d" % len(train))
    print("  valid : %d" % len(valid))
    print("  total : %d" % (len(train) + len(valid)))
    print()
    print("  system prompt in every example: %d chars (was 11881)" % len(prompt_corto))
    print("  languages        : %s" % dict(Counter(e["idioma"] for e in ejemplos).most_common()))
    print("  blocks           : %s" % dict(Counter(e["grupo"] for e in ejemplos).most_common()))
    print("  cases covered    : %d of %d" % (len(por_caso), len(casos) - len(reservados)))

    if reservados:
        colados = {e["caso"] for e in ejemplos} & reservados
        if colados:
            raise SystemExit("STOP: reserved cases leaked into the material: %s" % sorted(colados))
        print("  reserved cases   : NONE present (checked) — the exam stays honest")

    if args.solo_informe:
        print()
        print("  (--solo-informe: nothing written)")
        return

    os.makedirs(args.salida, exist_ok=True)
    for nombre, filas in (("train.jsonl", train), ("valid.jsonl", valid)):
        ruta = os.path.join(args.salida, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            for e in filas:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print("  wrote %s (%d lines, %d bytes)" % (ruta, len(filas), os.path.getsize(ruta)))

    # The tool schemas travel with the data: the model must see the SAME 29 tools.
    tools = json.load(open(os.path.join(BATERIA, "tools.json"), encoding="utf-8"))
    with open(os.path.join(args.salida, "tools.json"), "w", encoding="utf-8") as f:
        json.dump(tools, f, ensure_ascii=False, indent=1)
    print("  wrote %s (%d tools)" % (os.path.join(args.salida, "tools.json"),
                                     len(tools.get("tools", tools) if isinstance(tools, dict) else tools)))


if __name__ == "__main__":
    main()
