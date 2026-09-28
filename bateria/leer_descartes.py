#!/usr/bin/env python3
"""Read the discarded trajectories ONE BY ONE.

A discarded trajectory is a HYPOTHESIS about the model, never a verdict: the bench
has suspended good behaviour four times already in this project. So before counting a
discard as a model failure, read what the model actually did.

Usage:  python3 leer_descartes.py [etiqueta]
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ETQ = sys.argv[1] if len(sys.argv) > 1 else "fase1-r1-lambda"
MALO = os.path.join(BASE, "dataset_%s_descartado.jsonl" % ETQ)

QUIERO = sys.argv[2:] if len(sys.argv) > 2 else None

for ln in open(MALO, encoding="utf-8"):
    d = json.loads(ln)
    if QUIERO and not any(q in d["caso"] + d["idioma"] for q in QUIERO):
        continue
    print("=" * 96)
    print("%s  /  %s   (%s)   pasos=%s" % (d["caso"], d["idioma"], d["grupo"], d.get("pasos")))
    print("MOTIVO DEL DESCARTE: %s" % d.get("motivo_descarte"))
    print("=" * 96)
    for i, m in enumerate(d.get("mensajes") or []):
        rol = m.get("role")
        if rol == "system":
            print("  [%02d] system  (%d caracteres)" % (i, len(m.get("content") or "")))
            continue
        if rol == "user":
            print("  [%02d] USUARIO: %s" % (i, (m.get("content") or "")[:400]))
            continue
        if rol == "assistant":
            tc = m.get("tool_calls") or []
            raz = (m.get("reasoning_content") or "")[:600]
            if raz:
                print("  [%02d] PENSAMIENTO: %s" % (i, raz.replace("\n", " ")))
            if tc:
                for t in tc:
                    print("  [%02d] -> LLAMA A: %s %s"
                          % (i, t["function"]["name"], (t["function"].get("arguments") or "")[:220]))
            if m.get("content"):
                print("  [%02d] DICE: %s" % (i, (m["content"] or "")[:400].replace("\n", " ")))
            continue
        if rol == "tool":
            print("  [%02d] SALIDA REAL: %s" % (i, (m.get("content") or "")[:300].replace("\n", " | ")))
    print()
