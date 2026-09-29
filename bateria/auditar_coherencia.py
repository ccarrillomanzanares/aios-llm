#!/usr/bin/env python3
"""Coherence audit: the contradictions I already suspect, checked against the files.

This is not a model run and costs nothing. It only asks the documents and the result
files whether they agree with each other. Four suspicions, each one a claim that has
been made out loud in this project:

  1. The 4B has been quoted as 281/306, 282/306 AND 286/306. Only one can be current.
  2. The 35B has been quoted as 302/306 AND 304/306.
  3. The plan says "el andamiaje vale ~20 puntos: 72,4 % sin el frente a 92,2 % con el"
     -- but those two figures come from DIFFERENT benches (174 and 306), which is
     exactly what the plan itself says must never be done.
  4. Tool coverage: 25 tools demanded by the 41 generating cases, 5 by the 10 reserved
     ones, and 2 only in the reserved set. If that arithmetic is right the union is 27,
     not the 29 the project claims.
"""
import collections
import glob
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE)


def informe(nombre):
    p = os.path.join(BASE, "resultado_" + nombre)
    if not os.path.isfile(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    f = d.get("filas", [])
    ok = sum(1 for x in f if x.get("_ok"))
    tr = [x for x in f if x.get("tipo") == "trampa"]
    return {"fichero": nombre, "n": len(f), "ok": ok, "pct": round(100.0 * ok / max(1, len(f)), 1),
            "trampas": "%d/%d" % (sum(1 for x in tr if x.get("_ok")), len(tr))}


print("=" * 94)
print("1 y 2. TODOS LOS INFORMES DE RESULTADO QUE HAY EN DISCO")
print("=" * 94)
for p in sorted(glob.glob(os.path.join(BASE, "resultado_*.json"))):
    n = os.path.basename(p)[len("resultado_"):]
    i = informe(n)
    if i:
        print("  %-52s %3d filas  %3d ok  %5.1f %%  trampas %s"
              % (n, i["n"], i["ok"], i["pct"], i["trampas"]))

print()
print("=" * 94)
print("3. LA FRASE DEL PLAN: comparar 72,4 % con 92,2 %")
print("=" * 94)
for nombre in ("4b-prompt-corto-repuntuado.json", "4b-banco-completo-repuntuado.json",
               "4b-sin-thinking-repuntuado.json", "4b-corregido.json"):
    i = informe(nombre)
    if i:
        print("  %-40s banco de %3d  ->  %5.1f %%" % (nombre, i["n"], i["pct"]))
print("  Si la comparacion cruza bancos distintos, NO ES VALIDA (regla del propio plan).")

print()
print("=" * 94)
print("4. ARITMETICA DE LA COBERTURA DE HERRAMIENTAS")
print("=" * 94)
casos = json.load(open(os.path.join(BASE, "casos.json"), encoding="utf-8"))["casos"]
reserv = {l.split("#")[0].strip() for l in open(os.path.join(BASE, "holdout.txt"), encoding="utf-8")
          if l.split("#")[0].strip()}


def herrs(c):
    h = set()
    for k in ("esperado", "alternativas", "comprobacion"):
        v = c.get(k)
        if isinstance(v, dict) and v.get("herramienta"):
            h.add(v["herramienta"])
        elif isinstance(v, list):
            for e in v:
                if isinstance(e, dict) and e.get("herramienta"):
                    h.add(e["herramienta"])
    if c.get("herramienta"):
        h.add(c["herramienta"])
    return h


gen = set()
res = set()
for c in casos:
    (res if c["id"] in reserv else gen).update(herrs(c))

print("  herramientas exigidas por los 41 que GENERAN : %d" % len(gen))
print("  herramientas exigidas por los 10 RESERVADOS : %d" % len(res))
print("  solo en reservados                           : %s" % sorted(res - gen))
print("  solo en generadores                          : %d" % len(gen - res))
print("  en AMBOS                                     : %s" % sorted(gen & res))
print("  UNION (|gen| + |res| - |ambos|)              : %d" % len(gen | res))
print("  la cobertura que el proyecto afirma          : 29")
print("  -> si la union no da 29, o la extraccion de este script esta incompleta")
print("     o la afirmacion de 29/29 cuenta otra cosa")

# Where does the 29 come from? The real registry is the production tools file.
p = os.path.join(BASE, "tools.json")
if os.path.isfile(p):
    tools = json.load(open(p, encoding="utf-8"))
    if isinstance(tools, dict):
        tools = tools.get("tools", tools.get("herramientas", list(tools.values())[0]))
    nombres = [t.get("function", t).get("name") for t in tools]
    print()
    print("  el registro real de produccion (tools.json) tiene %d herramientas" % len(nombres))
    faltan = sorted(set(nombres) - (gen | res))
    print("  herramientas del registro que NINGUN caso exige: %s" % (faltan or "ninguna"))
    print("  -> con las dos cosas juntas la cobertura es %d de %d" % (len(set(nombres) & (gen | res)), len(nombres)))
