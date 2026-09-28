#!/usr/bin/env python3
"""Which numbers in PLAN-MAESTRO.md are stale, and what should they say now?

The project rule is that nothing is taken as good without a measurement. That rule
has been applied to the models and to the bench, but not to the plan itself: it
still quotes 27 Sep figures after the bench was corrected (172/174 -> 51 cases /
306 evaluations) and after both models were re-measured. A plan with stale numbers
is worse than no plan, because decisions get made on them.

This script does not rewrite anything. It lists every stale claim with its measured
replacement, so the edit is a mechanical list of substitutions rather than a sweep.
"""
import json, os, re, sys

BASE = "/home/ccmai/aios-llm"
PLAN = os.path.join(BASE, "PLAN-MAESTRO.md")

# ---------------------------------------------------------------- measured now
def leer(nombre):
    p = os.path.join(BASE, "bateria", nombre)
    if not os.path.isfile(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    f = d.get("filas", [])
    ok = sum(1 for x in f if x.get("_ok"))
    tr = [x for x in f if x.get("tipo") == "trampa"]
    trok = sum(1 for x in tr if x.get("_ok"))
    return {"n": len(f), "ok": ok, "pct": 100.0 * ok / max(1, len(f)),
            "trampas_n": len(tr), "trampas_ok": trok}

m4 = leer("resultado_4b-banco-completo-repuntuado.json")
m35 = leer("resultado_35b-banco-completo-repuntuado.json")
m4c = leer("resultado_4b-prompt-corto-repuntuado.json")

casos = json.load(open(os.path.join(BASE, "bateria", "casos.json"), encoding="utf-8"))
n_casos = len(casos["casos"])
n_idio = len(casos["idiomas"])

print("=" * 92)
print("MEDIDO HOY (lo que el plan deberia decir)")
print("=" * 92)
print("  banco            : %d casos x %d idiomas = %d evaluaciones   herramientas 29/29"
      % (n_casos, n_idio, n_casos * n_idio))
print("  4B + andamio     : %d/%d = %.1f%%   trampas %d/%d"
      % (m4["ok"], m4["n"], m4["pct"], m4["trampas_ok"], m4["trampas_n"]))
print("  4B sin andamio   : %d/%d = %.1f%%   trampas %d/%d"
      % (m4c["ok"], m4c["n"], m4c["pct"], m4c["trampas_ok"], m4c["trampas_n"]))
print("  35B (profesor)   : %d/%d = %.1f%%   trampas %d/%d"
      % (m35["ok"], m35["n"], m35["pct"], m35["trampas_ok"], m35["trampas_n"]))
print()

# --------------------------------------------------- where each stale number is
texto = open(PLAN, encoding="utf-8").read()
lineas = texto.split("\n")

# Each entry: what the plan says, and why it is stale / what it should say.
patrones = [
    ("162/174", "93,1 %% con el banco VIEJO de 174. Hoy: %d/%d = %.1f %%" % (m4["ok"], m4["n"], m4["pct"])),
    ("126/174", "72,4 %% sin andamio, banco viejo. Hoy se mide con 306: %d/%d = %.1f %%"
     % (m4c["ok"], m4c["n"], m4c["pct"])),
    ("154/174", "88,5 %% sin pensamiento, banco viejo. Hay que remedirlo con el banco de hoy"),
    ("172/174", "98,9 %% el 35B, banco viejo. Hoy: %d/%d = %.1f %%"
     % (m35["ok"], m35["n"], m35["pct"])),
    ("45/54", "trampas del 4B con andamio, banco viejo. Hoy: %d/%d" % (m4["trampas_ok"], m4["trampas_n"])),
    ("53/54", "trampas del 35B, banco viejo. Hoy: %d/%d" % (m35["trampas_ok"], m35["trampas_n"])),
    ("32/54", "trampas del 4B sin andamio, banco viejo. Hoy: %d/%d" % (m4c["trampas_ok"], m4c["trampas_n"])),
    ("174 evaluaciones", "el banco viejo. Hoy: %d evaluaciones" % (n_casos * n_idio)),
    ("12/30", "paquetes, cifra vieja de la tabla 3.1"),
    ("28/30", "paquetes, cifra vieja de la tabla 3.1"),
    ("22/30", "diagnostico, cifra vieja de la tabla 3.1"),
    ("30/30", "diagnostico, cifra vieja de la tabla 3.1"),
    ("5/13", "trampas, cifra vieja de la tabla 3.1"),
    ("10/13", "trampas, cifra vieja de la tabla 3.1"),
    ("18/18", "ficheros, cifra vieja de la tabla 3.1"),
    ("11/12", "procesos, cifra vieja de la tabla 3.1"),
    ("6/6", "red, cifra vieja de la tabla 3.1"),
    ("12/12", "escritorio/identidad, cifra vieja de la tabla 3.1"),
]

print("=" * 92)
print("DONDE ESTA CADA CIFRA OBSOLETA EN EL PLAN")
print("=" * 92)
for pat, nota in patrones:
    hits = [i + 1 for i, ln in enumerate(lineas) if pat in ln]
    if hits:
        print("  %-18s lineas %s  (%d sitios)" % (pat, ",".join(str(h) for h in hits[:12]), len(hits)))
        print("      -> %s" % nota)
    else:
        print("  %-18s (ya no aparece)" % pat)
print()
print("  (la tabla de §3.1 es la que mas ha envejecido: dice 'escriborio 12/12 -> No hace")
print("   falta dataset', y hoy escritorio es el SEGUNDO grupo que mas falla con andamio)")
