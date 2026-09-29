#!/usr/bin/env python3
"""Which result file is the CURRENT one, when several disagree?

The same model has been re-scored several times as the bench was corrected, so the
folder holds 282/306, 286/306 and 281/306 for the 4B, and 302/306 and 304/306 for the
35B. Only one can be current, and the way to tell is the FILE DATE plus what the
scoring actually changed -- not which number looks better.

The rule applied here: the bench was corrected and then re-scored, and the last
correction ADDED a check on the closing answer (`revisar_respuesta.py`) that catches
answers asserted without evidence. That check can only LOWER a score, so a later file
with a lower number is the honest one, and an older file with a higher number is a
score that the current scorer would not reproduce.
"""
import glob
import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))

filas = []
for p in glob.glob(os.path.join(BASE, "resultado_*.json")):
    n = os.path.basename(p)[len("resultado_"):]
    if "parcial" in n:
        continue
    if not any(k in n for k in ("4b", "35b")):
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    f = d.get("filas", [])
    if len(f) not in (174, 306):
        continue
    ok = sum(1 for x in f if x.get("_ok"))
    filas.append((os.path.getmtime(p), n, len(f), ok, round(100.0 * ok / len(f), 1)))

filas.sort()
print("=" * 100)
print("RESULT FILES FOR THE 4B AND THE 35B, OLDEST FIRST")
print("=" * 100)
print("%-22s %-46s %6s %6s %7s" % ("fecha", "fichero", "filas", "ok", "%"))
for t, n, nf, ok, pct in filas:
    print("%-22s %-46s %6d %6d %6.1f"
          % (time.strftime("%d %b %H:%M", time.localtime(t)), n, nf, ok, pct))

print()
print("=" * 100)
print("THE CURRENT ONE PER MODEL AND BENCH SIZE (the newest of each)")
print("=" * 100)
for clave in ("4b", "35b"):
    for banco in (174, 306):
        cand = [x for x in filas if x[1].startswith(clave) and x[2] == banco]
        if not cand:
            continue
        t, n, nf, ok, pct = cand[-1]
        otros = ["%s (%d/%d)" % (o[1], o[3], o[2]) for o in cand[:-1]]
        print("  %-4s banco %3d -> %-46s %d/%d = %.1f %%  %s"
              % (clave, banco, n, ok, nf, pct,
                 ("| SUPERSEDED: " + ", ".join(otros)) if otros else ""))

print()
print("NOTA: la correccion que AÑADIO el chequeo de la respuesta final")
print("      (revisar_respuesta.py) solo puede BAJAR una nota, asi que si un")
print("      fichero viejo tiene una nota MAS ALTA que el nuevo, esa nota alta")
print("      es una que el puntuador de hoy no reproduciria.")
