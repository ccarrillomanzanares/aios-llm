#!/usr/bin/env python3
"""The decisive comparison: cases where the 4B fails and the profesor passes.

That intersection is the ONLY thing extra material can fix. A case the 4B already
passes needs no material, and a case the profesor also fails cannot be learnt
from it -- it is a bench/hardware limit, not a lesson.

Also flags how many of those live in the reserved (holdout) cases: those can never
be trained on by design, so they set a floor on the score that no dataset can lift.
"""
import collections, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))


def cargar(nombre):
    d = json.load(open(os.path.join(BASE, nombre), encoding="utf-8"))
    r = {}
    for x in d.get("filas", []):
        r[(x["caso"], x["idioma"])] = bool(x.get("_ok"))
    return r


f4 = cargar("resultado_4b-banco-completo-repuntuado.json")
f35 = cargar("resultado_35b-banco-completo-repuntuado.json")
reservados = {l.split("#")[0].strip()
              for l in open(os.path.join(BASE, "holdout.txt"), encoding="utf-8")
              if l.split("#")[0].strip()}

comunes = sorted(set(f4) & set(f35))
print("evaluaciones comparables: %d (4B %d, 35B %d)" % (len(comunes), len(f4), len(f35)))
print()

arreglables = [(c, i) for (c, i) in comunes if not f4[(c, i)] and f35[(c, i)]]
limite = [(c, i) for (c, i) in comunes if not f4[(c, i)] and not f35[(c, i)]]
ya_ok = [(c, i) for (c, i) in comunes if f4[(c, i)]]

print("  el 4B YA acierta          : %3d   (no necesita material)" % len(ya_ok))
print("  el 4B falla y el profesor SI: %3d   <-- ESTO es lo unico que el material puede arreglar" % len(arreglables))
print("  el 4B falla y el profesor NO: %3d   (no es leccion: es el limite del banco)" % len(limite))
print()

print("LOS ARREGLABLES, por grupo:")
g = collections.Counter(c.split("-")[0] if False else c for (c, i) in arreglables)
por_grupo = collections.Counter()
for (c, i) in arreglables:
    por_grupo[c.rsplit("-", 1)[0].split("-")[0]] += 1
for k, v in por_grupo.most_common():
    print("   %-14s %d" % (k, v))
print()

print("LOS ARREGLABLES, por idioma:")
for k, v in collections.Counter(i for (c, i) in arreglables).most_common():
    print("   %-6s %d" % (k, v))
print()

dentro = [x for x in arreglables if x[0] in reservados]
fuera = [x for x in arreglables if x[0] not in reservados]
print("  de los arreglables, caen en casos RESERVADOS (nunca se entrenan): %d" % len(dentro))
print("  y se pueden atacar con material                                : %d" % len(fuera))
print()
print("  casos y evaluaciones que se pueden atacar de verdad:")
for (c, i) in sorted(fuera):
    print("     %-26s %s" % (c, i))
