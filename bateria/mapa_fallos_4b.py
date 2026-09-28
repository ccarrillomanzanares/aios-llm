#!/usr/bin/env python3
"""Where does the model we are going to TRAIN actually fail?

The 4B is the one being trained (the small model imitates the teacher), so its
failures are the map that says how much material each group needs. A group at 100%
gets no material: that is the ceiling the plan sets.
"""
import collections, json, sys

ruta = sys.argv[1] if len(sys.argv) > 1 else "resultado_4b-banco-completo-repuntuado.json"
d = json.load(open(ruta, encoding="utf-8"))
filas = d.get("filas", [])
print("informe:", ruta, "| evaluations:", len(filas))
print("claves de una fila:", sorted(filas[0].keys()) if filas else "-")
print()

# The scoring key has to be found, not assumed. `_ok` is the one repuntuar.py writes.
clave_ok = None
for k in ("_ok", "acierto", "ok", "correcto", "aprobado"):
    if k in filas[0]:
        clave_ok = k
        break
print("usando la clave de acierto:", clave_ok)
ok = sum(1 for x in filas if x.get(clave_ok))
print("aciertos: %d/%d = %.1f%%" % (ok, len(filas), 100.0 * ok / max(1, len(filas))))
print()

g = collections.defaultdict(lambda: {"n": 0, "f": 0})
idi = collections.defaultdict(lambda: {"n": 0, "f": 0})
for x in filas:
    gr = x.get("grupo", "?")
    g[gr]["n"] += 1
    idi[x.get("idioma", "?")]["n"] += 1
    if not x.get(clave_ok):
        g[gr]["f"] += 1
        idi[x.get("idioma", "?")]["f"] += 1

print("POR GRUPO - ordenado por FALLOS (los que mas material necesitan, arriba)")
print("%-14s %7s %7s %9s   %s" % ("grupo", "evals", "fallos", "acierto", "material que pide"))
for k in sorted(g, key=lambda k: -g[k]["f"]):
    t, f_ = g[k]["n"], g[k]["f"]
    pct = 100.0 * (t - f_) / t
    if f_ == 0:
        pedido = "NINGUNO (ya puntua al 100%)"
    elif pct < 80:
        pedido = "MUCHO (es donde esta el fallo)"
    else:
        pedido = "poco (repaso)"
    print("%-14s %7d %7d %8.1f%%   %s" % (k, t, f_, pct, pedido))

print()
print("POR IDIOMA (la hipotesis a comprobar: el espanol deberia ir mejor)")
print("%-6s %7s %7s %9s" % ("idioma", "evals", "fallos", "acierto"))
for k in sorted(idi):
    t, f_ = idi[k]["n"], idi[k]["f"]
    print("%-6s %7d %7d %8.1f%%" % (k, t, f_, 100.0 * (t - f_) / t))
