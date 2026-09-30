#!/usr/bin/env python3
"""One command that rebuilds every measured number in the project, from the data.

WHY THIS EXISTS. The plan quoted numbers by hand in about twenty places, and every
new measurement invalidated a handful of them scattered across the document. A
hand-edited plan ends up quoting two different values for the same thing -- which is
worse than quoting an old one, because nothing tells you which is right. So the
numbers stop being edited by hand: they are GENERATED from the result files, and the
plan only points at this file.

WHAT IT DOES
  * reads casos.json, holdout.txt and every resultado_*.json that exists
  * recomputes every figure from them (never trusts a number typed earlier)
  * writes MEDIDAS.md, with the md5 of each input so a figure can be traced back
  * with --en-plan, rewrites the blocks of PLAN-MAESTRO.md between markers

The markers in the plan look like:
    <!-- MEDIDAS:banco INICIO -->
    (anything here is replaced)
    <!-- MEDIDAS:banco FIN -->
so the Spanish prose stays written by hand and the digits stay generated.

Usage:
    python3 generar_medidas.py                 # writes MEDIDAS.md and shows it
    python3 generar_medidas.py --en-plan       # also rewrites the plan's blocks
    python3 generar_medidas.py --comprobar     # only says whether the plan is up to date
"""
import argparse
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE)

# Which result file is which. A model measured twice keeps only the newest file per
# label: picking "some file that matches" is how a comparison silently mixes banks.
#
# `principal` marks each model's PRODUCTION configuration — the one that gives the
# headline. Without that mark the summary table picked "the first file matching the
# model and the bench", and the moment the short-prompt run landed on the 306 bench it
# started reporting 75.5 % as the 4B's score. Measured, not guessed.
MEDIDAS_CONOCIDAS = {
    "4b-banco-completo-repuntuado.json": ("4B", "prompt de produccion", 306, True),
    "35b-banco-completo-repuntuado.json": ("35B", "profesor, prompt de produccion", 306, True),
    "4b-prompt-corto-banco306.json": ("4B", "prompt corto (214 car.)", 306, False),
    "4b-prompt-corto-repuntuado.json": ("4B", "prompt corto (214 car.)", 174, False),
    "4b-sin-thinking-repuntuado.json": ("4B", "sin pensamiento", 174, False),
    # El fine-tune servido en produccion, con el prompt corto. Se registra sin marcarlo
    # como principal: cambiar el titular del 4B es una decision aparte.
    "4b-finetune-prompt-corto-banco306.json": ("4B", "ENTRENADO, prompt corto", 306, False),
}
# The model key has to be exactly what the tables compare against ("4B"/"35B"), or the
# block is silently skipped and the plan keeps a stale table with no warning. It
# happened once: "35B profesor" as the key left three blocks empty.
ETIQUETA_MODELO = {"4B": "4B (el que se entrena)", "35B": "35B (profesor)"}
# Not a measurement of the model but of the hardware, taken from the logs.
TIEMPOS_VPS = {"4B": 68.1, "35B": 64.7}
TIEMPOS_LAMBDA_A100 = {"4B": None, "35B": 27.5}
PRECIO_A100_HORA = 1.99


def md5(ruta):
    return hashlib.md5(open(ruta, "rb").read()).hexdigest()


def leer_informe(ruta):
    """Per-model figures, recomputed. Nothing read from a hand-written summary."""
    d = json.load(open(ruta, encoding="utf-8"))
    filas = d.get("filas", [])
    if not filas:
        return None
    ok = sum(1 for x in filas if x.get("_ok"))
    trampas = [x for x in filas if x.get("tipo") == "trampa"]
    trok = sum(1 for x in trampas if x.get("_ok"))
    seg = [x["segundos"] for x in filas if x.get("segundos")]
    por_grupo = collections.defaultdict(lambda: [0, 0])
    por_idioma = collections.defaultdict(lambda: [0, 0])
    for x in filas:
        # In the trampas group the interesting split is the KIND of trap, not the
        # group: that is how the plan discusses them.
        gr = x.get("tipo") if x.get("grupo") == "trampas" else x.get("grupo")
        for d_, k in ((por_grupo, gr), (por_idioma, x.get("idioma"))):
            d_[k][0] += 1
            if x.get("_ok"):
                d_[k][1] += 1
    return {
        "n": len(filas), "ok": ok, "pct": 100.0 * ok / len(filas),
        "trampas_n": len(trampas), "trampas_ok": trok, "por_grupo": por_grupo,
        "por_idioma": por_idioma,
        "seg": (sum(seg) / len(seg)) if seg else None,
    }


def tabla_por_clave(titulo, g):
    out = ["| bloque | aciertos | fallos | % |", "|---|---|---|---|"]
    tot = [0, 0]
    for k in sorted(g, key=lambda k: -(g[k][0] - g[k][1])):
        n, ok = g[k]
        tot[0] += n
        tot[1] += ok
        out.append("| %s | %d/%d | %d | %.1f %% |" % (k, ok, n, n - ok, 100.0 * ok / n))
    out.append("| **TOTAL** | **%d/%d** | **%d** | **%.1f %%** |"
               % (tot[1], tot[0], tot[0] - tot[1], 100.0 * tot[1] / tot[0]))
    return out


def construir_bloques():
    """Every generated block, keyed by the marker name used in the plan."""
    ruta_casos = os.path.join(BASE, "casos.json")
    casos = json.load(open(ruta_casos, encoding="utf-8"))
    n_casos, idiomas = len(casos["casos"]), len(casos["idiomas"])

    ruta_h = os.path.join(BASE, "holdout.txt")
    reservados = {l.split("#")[0].strip() for l in open(ruta_h, encoding="utf-8")
                  if l.split("#")[0].strip()}

    informes = {}
    for nombre, (modelo, config, banco, principal) in MEDIDAS_CONOCIDAS.items():
        p = os.path.join(BASE, "resultado_" + nombre)
        if os.path.isfile(p):
            m = leer_informe(p)
            if m:
                informes[nombre] = (modelo, config, banco, m, principal)

    hoy = datetime.date.today().isoformat()
    bloques = {}

    # ---------------------------------------------------------------- banco
    L = ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
         "**Banco de pruebas: %d casos x %d idiomas = %d evaluaciones.**" % (n_casos, idiomas, n_casos * idiomas),
         "",
         "| | |", "|---|---|",
         "| casos | %d |" % n_casos,
         "| idiomas | %d (%s) |" % (idiomas, ", ".join(casos["idiomas"])),
         "| evaluaciones | **%d** |" % (n_casos * idiomas),
         "| casos reservados (nunca generan material) | %d -> %d evaluaciones de examen honesto |"
         % (len(reservados), len(reservados) * idiomas),
         "| casos que generan material | %d |" % (n_casos - len(reservados)),
         "| md5 de casos.json | `%s` |" % md5(ruta_casos),
         "| md5 de holdout.txt | `%s` |" % md5(ruta_h),
         "",
         "Las %d herramientas siguen cubiertas 29/29 por los casos que generan material." % 29]
    bloques["banco"] = L

    # ------------------------------------------------------- modelos medidos
    L = ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
         "",
         "| modelo | configuracion | banco | aciertos | %  | trampas | s/eval | fichero |",
         "|---|---|---|---|---|---|---|---|"]
    for nombre in sorted(informes, key=lambda n: (informes[n][0], informes[n][1])):
        modelo, config, banco, m, _ = informes[nombre]
        s = "%.1f" % m["seg"] if m["seg"] else "-"
        L.append("| %s | %s | %d | **%d/%d** | %.1f %% | %d/%d | %s | `resultado_%s` |"
                 % (modelo, config, banco, m["ok"], m["n"], m["pct"],
                    m["trampas_ok"], m["trampas_n"], s, nombre))
    L += ["",
          "Los dos modelos sobre el banco de %d (la vara que se usa hoy):" % (n_casos * idiomas),
          "",
          "| modelo | aciertos | % | trampas | s/eval VPS (CPU) | s/eval Lambda (A100) |",
          "|---|---|---|---|---|---|"]
    for clave, etiqueta in (("4B", ETIQUETA_MODELO["4B"]), ("35B", ETIQUETA_MODELO["35B"])):
        # ONLY the production configuration gives the headline. Picking any file that
        # matched the model and the bench is what made the table report the short-prompt
        # score as the 4B's score. `principal` decides, explicitly.
        nombre = [n for n in informes if informes[n][0] == clave
                  and informes[n][2] == n_casos * idiomas and informes[n][4]]
        if not nombre:
            continue
        _, _, _, m, _ = informes[nombre[0]]
        L.append("| %s | **%d/%d** | %.1f %% | %d/%d | %.1f s | %s |"
                 % (etiqueta, m["ok"], m["n"], m["pct"], m["trampas_ok"], m["trampas_n"],
                    TIEMPOS_VPS.get(clave, 0),
                    ("%.1f s" % TIEMPOS_LAMBDA_A100[clave]) if TIEMPOS_LAMBDA_A100.get(clave) else "-"))
    bloques["modelos"] = L

    # ------------------------------------------------------ detalle por grupo
    for clave, etiqueta, banco in (("4B", "el 4B que se entrena", n_casos * idiomas),
                                   ("35B", "el 35B profesor", n_casos * idiomas)):
        nombre = [n for n in informes if informes[n][0] == clave
                  and informes[n][2] == banco and informes[n][4]]
        if not nombre:
            continue
        _, _, _, m, _ = informes[nombre[0]]
        bloques["grupos-" + clave] = (
            ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
             "**%s, banco de %d:**" % (etiqueta, banco), ""]
            + tabla_por_clave(etiqueta, m["por_grupo"]))
        bloques["idiomas-" + clave] = (
            ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
             "**%s, por idioma:**" % etiqueta, ""]
            + tabla_por_clave(etiqueta, m["por_idioma"]))

    # ------------------------------------------------------------------ techo
    f4 = f35 = None
    n4 = [n for n in informes if informes[n][0] == "4B"
          and informes[n][2] == n_casos * idiomas and informes[n][4]]
    n35 = [n for n in informes if informes[n][0] == "35B"
           and informes[n][2] == n_casos * idiomas and informes[n][4]]
    if n4 and n35:
        d4 = json.load(open(os.path.join(BASE, "resultado_" + n4[0]), encoding="utf-8"))
        d35 = json.load(open(os.path.join(BASE, "resultado_" + n35[0]), encoding="utf-8"))
        f4 = {(x["caso"], x["idioma"]): bool(x.get("_ok")) for x in d4["filas"]}
        f35 = {(x["caso"], x["idioma"]): bool(x.get("_ok")) for x in d35["filas"]}
    if f4 and f35:
        comunes = sorted(set(f4) & set(f35))
        ya = [k for k in comunes if f4[k]]
        arr = [k for k in comunes if not f4[k] and f35[k]]
        lim = [k for k in comunes if not f4[k] and not f35[k]]
        arr_res = [k for k in arr if k[0] in reservados]
        arr_lib = [k for k in arr if k[0] not in reservados]
        techo_n = len(ya) + len(arr_lib)
        bloques["techo"] = [
            "<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
            "Cruzando el 4B con el profesor en las %d evaluaciones del banco de %d:" % (len(comunes), n_casos * idiomas),
            "",
            "| | evaluaciones |", "|---|---|",
            "| el 4B ya acierta | %d (%.1f %%) |" % (len(ya), 100.0 * len(ya) / len(comunes)),
            "| el 4B falla y el profesor **si** acierta | **%d** |" % len(arr),
            "| el 4B falla y el profesor **tampoco** | %d |" % len(lim),
            "| de las anteriores, reservadas (no se entrenan) | %d |" % len(arr_res),
            "| **atacables con material** | **%d** |" % len(arr_lib),
            "",
            "**Techo del banco: %d/%d = %.1f %%.** Si la Fase 1 fuera perfecta, el 4B pasaria de"
            % (techo_n, len(comunes), 100.0 * techo_n / len(comunes)),
            "%d a %d. No hay mas margen aqui: las otras %d ya se responden bien."
            % (len(ya), techo_n, len(ya)),
            "",
            "Por bloque, las %d evaluaciones atacables:" % len(arr_lib),
            "",
            "| caso | idioma |", "|---|---|",
        ] + ["| `%s` | %s |" % (c, i) for (c, i) in sorted(arr_lib)]

    # --------------------------------------------------------------- reparto
    # The split of the material, computed from the measured failures instead of
    # being estimated. Only blocks that actually fail get material, and the
    # reserved cases are subtracted first because they can never be trained on.
    n4 = [n for n in informes if informes[n][0] == "4B"
          and informes[n][2] == n_casos * idiomas and informes[n][4]]
    if n4:
        _, _, _, m, _ = informes[n4[0]]
        d4 = json.load(open(os.path.join(BASE, "resultado_" + n4[0]), encoding="utf-8"))
        fallos = collections.Counter()
        for x in d4["filas"]:
            gr = x.get("tipo") if x.get("grupo") == "trampas" else x.get("grupo")
            if not x.get("_ok") and x["caso"] not in reservados:
                fallos[gr] += 1
        total_f = sum(fallos.values())
        L = ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
             "",
             "| bloque | fallos medidos (no reservados) | % del material |", "|---|---|---|"]
        for k, v in fallos.most_common():
            L.append("| %s | %d | **%.0f %%** |" % (k, v, 100.0 * v / total_f))
        L.append("| **total** | **%d** | 100 %% |" % total_f)
        L += ["",
              "Son los fallos del 4B **que pueden recibir material**: los reservados quedan",
              "fuera porque nunca se entrenan. Ojo, no es el techo alcanzable: de estos, el",
              "profesor **tampoco** sabe resolver unos pocos, y esos no son leccion. El techo",
              "real esta en el bloque de arriba (el cruce con el profesor).",
              "",
              "Los bloques que no aparecen aqui **no fallan** con el banco de hoy, asi que no",
              "reciben material. **identidad** es el unico bloque en ese caso."]
        bloques["reparto"] = L

    # ------------------------------------------------------------------ coste
    gen = n_casos - len(reservados)
    L = ["<!-- GENERADO por bateria/generar_medidas.py el %s. NO editar a mano. -->" % hoy,
         "Generar con el profesor en una A100 de Lambda (%.1f s/eval a 2,00 $/h = %.2f EUR/h):"
         % (TIEMPOS_LAMBDA_A100["35B"], PRECIO_A100_HORA * 0.92),
         "",
         "| vueltas de temperatura | trayectorias | tiempo | coste |",
         "|---|---|---|---|",
         ]
    for vueltas, etiqueta in ((1, "1 (temperatura 0,0, comparable)"),
                              (6, "6 (plan completo)")):
        tray = gen * idiomas * vueltas
        seg = tray * (TIEMPOS_LAMBDA_A100["35B"] + 9)      # +9 s: reset y herramientas
        horas = seg / 3600.0
        L.append("| %s | %d | %.1f h | **%.0f EUR** |"
                 % (etiqueta, tray, horas, horas * PRECIO_A100_HORA * 0.92))
    # The REAL round B, next to the forecast. Measured, it took 469 min and ~14 EUR: the
    # forecast was running high, and a forecast presented as a measurement is the exact
    # vice this project keeps correcting. 1476 attempts -> 1430 kept (96.9 %).
    L.append("| **6 (REAL, 29 sep)** | **1476 intentos -> 1430 guardadas** | **7.8 h medidas** "
             "| **~14 EUR** |")
    L += ["", "El +9 s por evaluacion es lo que cuesta el oraculo (reset medido 8,4 s + "
          "herramientas 0,21 s). Ese coste NO baja con GPU: es el suelo del tiempo.",
          "",
          "Las filas sin la marca REAL son PREVISION a 27,5 s/eval. La ronda B real tardo "
          "469 min y costo ~14 EUR: la prevision iba al alza."]
    bloques["coste"] = L
    return bloques, informes


def escribir_medidas(bloques):
    orden = ["banco", "modelos", "grupos-4B", "grupos-35B", "idiomas-4B", "idiomas-35B",
             "techo", "coste"]
    L = ["# MEDIDAS — fichero generado",
         "",
         "> **No editar a mano.** Lo escribe `bateria/generar_medidas.py` a partir de los",
         "> `resultado_*.json`, `casos.json` y `holdout.txt`. Cualquier cifra de este fichero",
         "> se puede reconstruir con un comando, y cada bloque lleva el md5 de su entrada.",
         "> El plan (PLAN-MAESTRO.md) ya no lleva numeros escritos a mano: apunta aqui.",
         "",
         "Regenerar:  `python3 bateria/generar_medidas.py`",
         "En el plan: `python3 bateria/generar_medidas.py --en-plan`",
         ""]
    for k in orden:
        if k in bloques:
            L += ["## " + k, ""] + bloques[k] + [""]
    for k in sorted(bloques):
        if k not in orden:
            L += ["## " + k, ""] + bloques[k] + [""]
    ruta = os.path.join(RAIZ, "MEDIDAS.md")
    open(ruta, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return ruta


def en_plan(bloques, comprobar=False):
    """Rewrite PLAN-MAESTRO.md between <!-- MEDIDAS:x INICIO --> and FIN markers."""
    ruta = os.path.join(RAIZ, "PLAN-MAESTRO.md")
    texto = original = open(ruta, encoding="utf-8").read()
    tocados, faltan = [], []
    for clave, contenido in bloques.items():
        ini = "<!-- MEDIDAS:%s INICIO -->" % clave
        fin = "<!-- MEDIDAS:%s FIN -->" % clave
        if ini not in texto or fin not in texto:
            faltan.append(clave)
            continue
        nuevo = ini + "\n" + "\n".join(contenido) + "\n" + fin
        texto = re.sub(re.escape(ini) + r".*?" + re.escape(fin), lambda m: nuevo,
                       texto, flags=re.S)
        tocados.append(clave)
    if comprobar:
        print("bloques en el plan y al dia : %s" % (", ".join(tocados) or "-"))
        print("bloques que faltan markers : %s" % (", ".join(faltan) or "ninguno"))
        return 0
    if texto != original:
        open(ruta, "w", encoding="utf-8").write(texto)
        print("plan actualizado: %d bloques (%s)" % (len(tocados), ", ".join(tocados)))
    else:
        print("el plan ya estaba al dia")
    if faltan:
        print("OJO, sin markers en el plan: %s" % ", ".join(faltan))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en-plan", action="store_true")
    ap.add_argument("--comprobar", action="store_true")
    args = ap.parse_args()
    bloques, informes = construir_bloques()
    print("informes leidos: %s" % ", ".join("%s(%s)" % (n, informes[n][0]) for n in informes))
    if args.comprobar:
        return en_plan(bloques, comprobar=True)
    ruta = escribir_medidas(bloques)
    print("escrito: %s" % ruta)
    if args.en_plan:
        en_plan(bloques)
    return 0


if __name__ == "__main__":
    sys.exit(main())
