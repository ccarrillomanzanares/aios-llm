#!/usr/bin/env python3
"""Turn the round into generated numbers, so the plan cannot drift again.

Round 1 (fase1-r1-lambda) was generated BEFORE two verdicts were corrected, so its
summary line (238/246) is not the material that will actually be trained on: two
trajectories were discarded by a bug in the filter and have since been recovered
(trampa-git-inyeccion en+pt). The material is therefore round 1's kept set, minus the
two wrongly-discarded ones, plus the recovered pair.

This script rebuilds that honestly and adds the result to bateria/medidas-fase1.json,
which generar_medidas.py does not know about (it reads the bench's resultado_*.json).
Keeping the two apart on purpose: the bench measures a MODEL, this measures the
MATERIAL. Mixing them is how a bench number and a dataset number get confused.
"""
import collections
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ETQ = "fase1-r1-lambda"


def leer(nombre):
    ruta = os.path.join(BASE, nombre)
    if not os.path.isfile(ruta):
        return []
    return [json.loads(l) for l in open(ruta, encoding="utf-8")]


bueno = leer("dataset_%s.jsonl" % ETQ)
malo = leer("dataset_%s_descartado.jsonl" % ETQ)
rec = leer("dataset_recuperar-git.jsonl")

# The two that were discarded by the filter bug and have been re-generated.
recuperadas = {(d["caso"], d["idioma"]) for d in rec}
malo_efectivo = [d for d in malo if (d["caso"], d["idioma"]) not in recuperadas]

total = len(bueno) + len(rec)
intentos = total + len(malo_efectivo)

por_grupo = collections.defaultdict(lambda: [0, 0])
for d in bueno + rec:
    por_grupo[d["grupo"]][0] += 1
for d in malo_efectivo:
    por_grupo[d["grupo"]][1] += 1

por_idioma = collections.Counter(d["idioma"] for d in bueno + rec)
caracteres = sum(len(json.dumps(d["mensajes"], ensure_ascii=False)) for d in bueno + rec)
pasos = [d.get("pasos") or 0 for d in bueno + rec]

motivos = collections.Counter((d.get("motivo_descarte") or "").split(":")[0][:60]
                              for d in malo_efectivo)

out = {
    "etiqueta": ETQ,
    "profesor": "Qwen3.6-35B-A3B-UD-Q4_K_M en Lambda A100 (tunel SSH desde el VPS)",
    "que_es": "Material de la Fase 1, ronda 1. NO es una medida de un modelo: es el material.",
    "trayectorias_verificadas": total,
    "intentos": intentos,
    "pasa_el_filtro_pct": round(100.0 * total / max(1, intentos), 1),
    "recuperadas_por_arreglo_del_filtro": sorted("%s/%s" % k for k in recuperadas),
    "descartes_reales": len(malo_efectivo),
    "por_grupo": {k: {"ok": v[0], "descartadas": v[1]} for k, v in sorted(por_grupo.items())},
    "por_idioma": dict(sorted(por_idioma.items())),
    "caracteres": caracteres,
    "tokens_aprox": caracteres // 4,
    "pasos": {"min": min(pasos), "media": round(sum(pasos) / len(pasos), 1), "max": max(pasos)},
    "motivos_de_descarte": dict(motivos.most_common()),
    "coste": {"minutos": 77, "precio_a100_eur_h": 1.83,
              "eur": round(77 / 60.0 * 1.83, 2)},
    "nota": "Dos herramientas (process_list, read_identity) solo las piden casos reservados, "
            "asi que NO tendran material nunca. El material cubre 25 de las 29.",
}
ruta = os.path.join(BASE, "medidas-fase1.json")
json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
print("\nescrito: %s" % ruta)
