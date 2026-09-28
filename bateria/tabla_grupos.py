#!/usr/bin/env python3
"""Print the current per-group table, ready to paste into the plan.

Kept as a script so the plan can be refreshed from measurements instead of by hand:
the numbers in it have already gone stale once, and a plan that has to be edited by
eye is a plan that drifts again next week.
"""
import collections, json, os, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)))


def grupos(nombre):
    d = json.load(open(os.path.join(BASE, nombre), encoding="utf-8"))
    g = collections.defaultdict(lambda: [0, 0])
    for x in d["filas"]:
        gr = x.get("tipo") if x.get("grupo") == "trampas" else x.get("grupo")
        g[gr][0] += 1
        if x.get("_ok"):
            g[gr][1] += 1
    return g


def tabla(g, etiqueta):
    print("\n### %s" % etiqueta)
    print("| bloque | aciertos | fallos | % |")
    print("|---|---|---|---|")
    tot = [0, 0]
    for k in sorted(g, key=lambda k: -(g[k][0] - g[k][1])):
        n, ok = g[k]
        tot[0] += n
        tot[1] += ok
        print("| %s | %d/%d | %d | %.1f %% |" % (k, ok, n, n - ok, 100.0 * ok / n))
    print("| **TOTAL** | **%d/%d** | **%d** | **%.1f %%** |"
          % (tot[1], tot[0], tot[0] - tot[1], 100.0 * tot[1] / tot[0]))


g35 = grupos("resultado_35b-banco-completo-repuntuado.json")
g4 = grupos("resultado_4b-banco-completo-repuntuado.json")
g4c = grupos("resultado_4b-prompt-corto-repuntuado.json")

tabla(g4, "4B CON andamiaje (banco de 306, medido 28 sep)")
tabla(g35, "35B profesor (banco de 306, medido 28 sep)")
tabla(g4c, "4B SIN andamiaje / prompt corto (banco de 174, medido 27 sep -- pendiente de repetir)")
