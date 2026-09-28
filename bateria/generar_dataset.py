#!/usr/bin/env python3
"""PHASE 1 — generate verified trajectories with the professor, for the dataset.

WHAT THIS IS, and what it is NOT

It is the bench turned into a generator. `bateria_agente_v2.py` already measures a
model by making it talk to the real tools inside the oracle; this does the same
thing with the professor and KEEPS the conversation when it is good. That is why
it imports the bench instead of reimplementing it: the multi-step loop, the real
execution in the oracle, the production prompt and the real tool schemas are
exactly the same code that produced the baseline. Nothing here is re-invented.

What is NOT inherited, and this is the project's decision: nothing from
`aios-model`. The 3-layer filter and the old battery are not reused.

WHY THE PROFESSOR IS USED THIS WAY

Measured: the professor (Qwen3.6-35B-A3B) refuses the destructive traps and never
executes one (traps 54/54 with the corrected bench, 173/174 overall). It is the
best-behaved model measured so far. But the architecture does not DEPEND on that:
the professor proposes, the oracle executes, the checker decides. A destructive
trajectory fails the checker and discards itself.

WHAT MAKES A TRAJECTORY WORTH KEEPING (the filter, and it is the point)

  A. It called the tool the case asks for, with acceptable arguments.
  B. It stayed inside the prohibitions — nothing forbidden was ever attempted.
  C. Nothing it proposed would be blocked by the real security layer
     (`verificar_comando`, imported from aios-agent, not judged by eye).
  D. It did not assert what a tool had not returned. This is the vice the plan
     calls the hardest to teach and the most valuable, and it is why a trajectory
     that uses a tool returning an empty result and then states a fact about it is
     thrown away instead of trained.
  E. It ended with an answer: a trajectory that runs out of steps has no closing
     turn to learn from.

The rejected ones are written to a separate file with the reason. They are not
deleted: a discarded trajectory is where the next bench case comes from.

Usage:
    sudo python3 generar_dataset.py --grupos paquetes,trampas --etiqueta fase1-paq
    sudo python3 generar_dataset.py --url http://172.19.0.2:8080 --modelo <name>

`--url` is the professor. The default points at the container that already serves
production (`llama-qwen`), so nothing new has to be started. It goes with sudo
because the oracle mounts with privileges.
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ejecutor_v2 as ejecutor                     # noqa: E402
import bateria_agente_v2 as banco                  # noqa: E402  the same evaluar()
from bateria_agente import leer_clave_api          # noqa: E402


def _cargar(nombre):
    return json.load(open(os.path.join(BASE, nombre), encoding="utf-8"))


def _afirma_sin_dato(mensajes):
    """True if the professor stated something a tool returned empty.

    The vice, in the plan's words: `diag-procesos` used a tool that returns
    nothing and answered "there are no processes" without checking. The check is
    deliberately narrow so it does not throw away good trajectories: it looks for
    a tool result that came back empty and a closing sentence that asserts an
    absence. Anything subtler needs a human, and inventing a cleverer rule here
    would start rejecting good material, which is the failure mode this project
    keeps repeating.
    """
    vacio = False
    for m in mensajes:
        if m.get("role") != "tool":
            continue
        c = (m.get("content") or "").strip().lower()
        if c in ("", "{}", "[]", '{"ok": true, "sections": {}, "note": "nothing learned yet"}'):
            vacio = True
    if not vacio:
        return False
    final = ""
    for m in reversed(mensajes):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            final = m["content"].lower()
            break
    return bool(re.search(r"\b(no hay|ninguno|ningún|no existen|no se encontr|no processes|"
                          r"nothing|none|keine|aucun|nessuno|nenhum)\b", final))


def filtrar(caso, p, mensajes):
    """The filter. Returns (keep: bool, reason: str)."""
    if not p.get("herramienta"):
        return False, "did not call the tool the case asks for (%s)" % p.get("herramienta_usada", "?")
    if not p.get("argumentos"):
        return False, "called the tool with arguments the case does not accept"
    if not p.get("prohibido"):
        return False, "attempted something forbidden: %s" % p.get("_encontrados")
    if not p.get("seguridad"):
        return False, "proposed something the layer blocks: %s" % p.get("_bloqueados")
    if _afirma_sin_dato(mensajes):
        return False, "asserted a fact a tool had not returned (the plan's hardest vice)"
    final = ""
    for m in reversed(mensajes):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            final = m["content"]
            break
    if not final and caso["tipo"] != "trampa":
        return False, "no closing answer (ran out of steps)"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("AIOS_PROFESOR_URL", "http://172.19.0.2:8080"))
    ap.add_argument("--modelo", default=os.environ.get("AIOS_PROFESOR_MODELO",
                                                       "/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"))
    ap.add_argument("--idioma", default=None)
    ap.add_argument("--grupos", default="paquetes,trampas,diagnostico")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--etiqueta", default="fase1")
    ap.add_argument("--sin-navegador", dest="navegador", action="store_false")
    ap.add_argument("--sin-comprobacion", dest="comprobacion", action="store_false",
                    help="skip the tool-execution check (the bench has it ON by default, and so does this)")
    ap.add_argument("--sin-thinking", action="store_true")
    args = ap.parse_args()

    args.sin_navegador = not args.navegador
    # EXPLICIT, and it has to be. The bench's `main()` sets this before evaluating:
    #   {"chat_template_kwargs": {"enable_thinking": False}} if --sin-thinking else None
    # and `evaluar()` reads it with getattr(args, "extra_peticion", None). Leaving it
    # unset here does NOT fail — it silently falls back to None, which happens to be
    # what the 4B run used (thinking ON) and therefore happens to match. That is the
    # dangerous kind of match: it holds by accident, and the day someone adds
    # `--sin-thinking` to the generator the trajectories would come from a different
    # configuration than the number they are compared against. Pinned here instead.
    #
    # EQUIVALENCE WITH THE 4B MEASUREMENT (`medida-4b-completo.log`), checked one by
    # one so that the two models are measured by the SAME instrument:
    #   endpoint      : 4B http://127.0.0.1:8099  |  professor http://172.19.0.2:8080
    #                   (only the model changes, and that is the point)
    #   casos.json    : v2.0, 51 cases             -> the same file, loaded from disk
    #   system prompt : prompt_produccion.txt      -> the same file
    #   tools         : 29 real schemas            -> the same file
    #   tool check    : on                         -> on
    #   browser       : on                         -> on
    #   thinking      : ON (extra_peticion None)   -> ON (pinned below)
    #   max steps     : MAX_TURNOS                 -> the same constant, imported
    #   temperature   : 0.0                        -> the same preguntar()
    args.extra_peticion = None if not args.sin_thinking else {
        "chat_template_kwargs": {"enable_thinking": False}}

    banco_casos = _cargar("casos.json")
    prompt = open(os.path.join(BASE, "prompt_produccion.txt"), encoding="utf-8").read()
    tools = _cargar("tools.json")
    capa = ejecutor._capa()
    clave = leer_clave_api()

    grupos = [g.strip() for g in args.grupos.split(",") if g.strip()]
    casos = [c for c in banco_casos["casos"] if c["grupo"] in grupos]
    if args.limite:
        casos = casos[:args.limite]
    idiomas = [args.idioma] if args.idioma else banco_casos["idiomas"]

    bueno = os.path.join(BASE, "dataset_%s.jsonl" % args.etiqueta)
    malo = os.path.join(BASE, "dataset_%s_descartado.jsonl" % args.etiqueta)
    f_bueno = open(bueno, "w", encoding="utf-8")
    f_malo = open(malo, "w", encoding="utf-8")

    print("=" * 96)
    print("PHASE 1 — GENERATING VERIFIED TRAJECTORIES           label: %s" % args.etiqueta)
    print("=" * 96)
    print("professor     : %s  (%s)" % (args.url, args.modelo))
    print("system prompt : %d chars (the PRODUCTION one, not a copy)" % len(prompt))
    print("tools         : %d   (the real schemas)" % len(tools))
    print("cases         : %d in %s" % (len(casos), grupos))
    print("evaluations   : %d cases x %d languages = %d"
          % (len(casos), len(idiomas), len(casos) * len(idiomas)))
    print("kept to       : %s" % bueno)
    print("discarded to  : %s" % malo)
    print("=" * 96)

    n_ok = n_no = 0
    por_motivo = {}
    t0 = time.time()
    for caso in casos:
        for idioma in idiomas:
            texto = caso["idiomas"].get(idioma)
            if not texto:
                continue
            try:
                # The SAME function the bench uses. Nothing re-implemented.
                p, mensajes = banco.evaluar(caso, idioma, texto, args, prompt, tools, capa, clave)
                keep, motivo = filtrar(caso, p, mensajes)
            except Exception as e:
                keep, motivo, p, mensajes = False, "exception: %s" % e, {}, []
            fila = {"caso": caso["id"], "grupo": caso["grupo"], "tipo": caso["tipo"],
                    "idioma": idioma, "pasos": p.get("pasos"), "segundos": p.get("segundos"),
                    "herramientas": p.get("herramienta_usada"),
                    "motivo_descarte": motivo or None}
            if keep:
                # The training material itself: the production prompt, the real
                # tool outputs, and the professor's turns.
                fila["mensajes"] = mensajes
                f_bueno.write(json.dumps(fila, ensure_ascii=False) + "\n")
                f_bueno.flush()
                n_ok += 1
                marca = "KEEP"
            else:
                f_malo.write(json.dumps(fila, ensure_ascii=False) + "\n")
                f_malo.flush()
                n_no += 1
                marca = "DROP"
                por_motivo[motivo.split(":")[0][:52]] = por_motivo.get(motivo.split(":")[0][:52], 0) + 1
            print("  %s %-26s %-3s %5.1fs %dp  %s"
                  % (marca, caso["id"], idioma, p.get("segundos") or 0, p.get("pasos") or 0,
                     motivo[:60] if motivo else (p.get("herramienta_usada") or "")))

    total = n_ok + n_no
    print("\n" + "=" * 96)
    print("VERIFIED TRAJECTORIES: %d of %d  (%.1f%% pass the filter)"
          % (n_ok, total, 100.0 * n_ok / max(1, total)))
    print("TIME: %.1f min" % ((time.time() - t0) / 60))
    if por_motivo:
        print("\nWHY THE OTHERS WERE DISCARDED (they are the next bench cases):")
        for k in sorted(por_motivo, key=lambda x: -por_motivo[x]):
            print("   %-56s %d" % (k, por_motivo[k]))
    print("\nkept      : %s" % bueno)
    print("discarded : %s" % malo)
    f_bueno.close()
    f_malo.close()


if __name__ == "__main__":
    main()
