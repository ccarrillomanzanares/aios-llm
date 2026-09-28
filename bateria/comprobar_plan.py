#!/usr/bin/env python3
"""Fail if a stale figure is loose in PLAN-MAESTRO.md.

THE PROBLEM THIS SOLVES. The plan used to carry measured numbers written by hand in
about twenty places. Every new measurement invalidated a handful of them, scattered
across the document, and the plan ended up quoting two different values for the same
thing -- worse than quoting an old one, because nothing tells you which is right.

THE FIX, in two parts:
  1. every measured figure is GENERATED into the plan between <!-- MEDIDAS:x --> markers
     (bateria/generar_medidas.py);
  2. this check fails the moment a superseded figure appears OUTSIDE those markers.

So the numbers cannot drift silently again. Exit code is 1 when it finds something,
which is what makes it usable as a gate before committing.

Usage:
    python3 comprobar_plan.py          # report
    python3 comprobar_plan.py --fallar # exit 1 if stale figures are loose
"""
import argparse
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(RAIZ, "PLAN-MAESTRO.md")

# Figures that have been superseded by a re-measurement. Each one is listed with what
# replaced it, so the report says what to write instead of only what is wrong.
# KEEP THIS LIST GROWING: every time a number is re-measured, its old value belongs
# here, and that is the whole point of the check.
SUPERADAS = {
    "162/174": "4B con andamio, banco de 174 -> hoy 282/306 = 92,2 %",
    "172/174": "35B, banco de 174 -> hoy 302/306 = 98,7 %",
    "154/174": "4B sin pensamiento, banco de 174 -> hay que re-medirlo con el banco de 306",
    "126/174": "4B con prompt corto, banco de 174 -> hay que re-medirlo con el banco de 306",
    "98,9 %": "35B, banco de 174 -> hoy 98,7 %",
    "93,1 %": "4B con andamio, banco de 174 -> hoy 92,2 %",
    "88,5 %": "4B sin pensamiento, banco de 174 -> sin re-medir",
    "45/54": "trampas del 4B con andamio, banco de 174 -> hoy 80/84",
    "53/54": "trampas del 35B, banco de 174 -> hoy 84/84",
    "32/54": "trampas del 4B con prompt corto, banco de 174 -> sin re-medir",
    "174 evaluaciones": "el banco viejo -> hoy 306 evaluaciones",
    "29 casos × 6 idiomas = 174": "el banco viejo -> hoy 51 casos x 6 = 306",
}

# Contexts where an old figure is legitimate: it is being QUOTED as history on purpose.
# The markers are stripped before the scan, so anything inside them is already ignored.
EXENTAS = (
    "Epoch 1",
    "banco de 174",
    "banco viejo",
    "ronda histórica",
    "historica",
    "quedan registradas en `MEDIDAS.md`",
    "SUPERADAS",
)


def sin_bloques_generados(texto):
    """Drop everything between the MEDIDAS markers: that part IS the current numbers."""
    return re.sub(r"<!-- MEDIDAS:.*?-->.*?<!-- MEDIDAS:.*?-->", "", texto, flags=re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallar", action="store_true",
                    help="exit 1 if it finds stale figures outside the generated blocks")
    args = ap.parse_args()

    if not os.path.isfile(PLAN):
        print("no encuentro %s" % PLAN)
        return 1
    lineas = open(PLAN, encoding="utf-8").read().split("\n")

    # Only lines OUTSIDE the generated blocks are suspect, and a line that is openly
    # talking about the old bench is not a mistake: it is the plan being honest about
    # its history. Everything else has to be either generated or not a number.
    dentro = False
    culpables = []
    exentas = 0
    for i, ln in enumerate(lineas, 1):
        if "MEDIDAS:" in ln and "INICIO" in ln:
            dentro = True
            continue
        if "MEDIDAS:" in ln and "FIN" in ln:
            dentro = False
            continue
        if dentro:
            continue
        if any(t in ln for t in EXENTAS):
            exentas += 1
            continue
        for pat, reemplazo in SUPERADAS.items():
            if pat in ln:
                culpables.append((i, pat, reemplazo, ln.strip()[:96]))
                break

    if not culpables:
        print("OK: ninguna cifra superada suelta en el plan.")
        print("Los numeros del plan salen de los bloques generados (bateria/generar_medidas.py).")
        print("Lineas exentas por hablar abiertamente del banco viejo: %d" % exentas)
        return 0

    print("CIFRAS SUPERADAS SUELTAS EN EL PLAN (%d):" % len(culpables))
    print()
    for i, pat, reemplazo, txt in culpables:
        print("  linea %-4d  %-16s -> %s" % (i, pat, reemplazo))
        print("      %s" % txt)
    print()
    print("Arreglo: o se quita la cifra y se apunta a MEDIDAS.md, o se mete dentro de un")
    print("bloque <!-- MEDIDAS:x INICIO --> ... <!-- MEDIDAS:x FIN --> para que se genere.")
    return 1 if args.fallar else 0


if __name__ == "__main__":
    sys.exit(main())
