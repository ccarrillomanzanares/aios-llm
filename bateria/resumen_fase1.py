#!/usr/bin/env python3
"""What did round 1 actually produce, and what do the 8 discards teach?

The discarded trajectories are NOT failures to hide: each one is a candidate for the
next bench case, and the motive tells you which kind. This prints the breakdown by
group, by language, and the discards one by one.
"""
import collections
import json
import os
import sys

BASE = "/home/ccmai/aios-llm/bateria"
ETQ = sys.argv[1] if len(sys.argv) > 1 else "fase1-r1-lambda"

bueno = os.path.join(BASE, "dataset_%s.jsonl" % ETQ)
malo = os.path.join(BASE, "dataset_%s_descartado.jsonl" % ETQ)

res = {}
for ln in open(bueno, encoding="utf-8"):
    d = json.loads(ln)
    res[(d["caso"], d["idioma"])] = d

des = [json.loads(ln) for ln in open(malo, encoding="utf-8")]

print("=" * 92)
print("ROUND 1 — WHAT CAME OUT")
print("=" * 92)
print("  verified trajectories : %d" % len(res))
print("  discarded             : %d" % len(des))
print("  pass rate             : %.1f %%" % (100.0 * len(res) / max(1, len(res) + len(des))))
print()

# ---- volume in tokens: this is what the training will actually consume
chars = 0
pasos = []
for d in res.values():
    chars += len(json.dumps(d["mensajes"], ensure_ascii=False))
    pasos.append(d.get("pasos") or 0)
print("  volume                : %d caracteres (~%d tokens, /4)" % (chars, chars // 4))
print("  steps per trajectory  : min %d  media %.1f  max %d"
      % (min(pasos), sum(pasos) / len(pasos), max(pasos)))
print()

# ---- by group
g = collections.defaultdict(lambda: [0, 0])
for d in res.values():
    gr = d["grupo"]
    g[gr][0] += 1
for d in des:
    g[d["grupo"]][1] += 1
print("BY GROUP (kept / discarded):")
for k in sorted(g, key=lambda k: -sum(g[k])):
    ok, no = g[k]
    print("   %-14s %3d guardadas  %d descartadas" % (k, ok, no))
print()

# ---- by language
idi = collections.Counter(d["idioma"] for d in res.values())
print("BY LANGUAGE (kept):")
for k in sorted(idi):
    print("   %-4s %3d" % (k, idi[k]))
print()

# ---- the discards, one by one: they are next week's bench cases
print("THE DISCARDED ONES, ONE BY ONE (each is a candidate bench case):")
for d in sorted(des, key=lambda x: (x["grupo"], x["caso"], x["idioma"])):
    print("   %-26s %-3s %2dp  %s" % (d["caso"], d["idioma"], d.get("pasos") or 0,
                                      (d.get("motivo_descarte") or "")[:60]))
print()

# ---- which blocks are still uncovered: the map said paquetes/diagnostico matter most
print("COVERAGE OF THE 29 TOOLS BY THE KEPT MATERIAL:")
casos = json.load(open(os.path.join(BASE, "casos.json"), encoding="utf-8"))["casos"]
por_id = {c["id"]: c for c in casos}
herr = set()
for (caso, _) in res:
    c = por_id.get(caso)
    if not c:
        continue
    for k in ("esperado", "alternativas", "comprobacion"):
        v = c.get(k)
        if isinstance(v, dict) and v.get("herramienta"):
            herr.add(v["herramienta"])
        elif isinstance(v, list):
            for e in v:
                if isinstance(e, dict) and e.get("herramienta"):
                    herr.add(e["herramienta"])
    if c.get("herramienta"):
        herr.add(c["herramienta"])
print("   herramientas distintas que aparecen en el material: %d" % len(herr))
print("   %s" % ", ".join(sorted(herr)))
