#!/usr/bin/env python3
"""Compare the fine-tuned 4B against the two baselines, and say whether it worked.

Reads three result files that all come from the SAME harness, the SAME bench (51 cases x
6 languages = 306) and the SAME short prompt, so the comparison is like for like:

  resultado_4b-prompt-corto-banco306.json   stock 4B, short prompt  -> 231/306 = 75.5 %
  resultado_4b-finetune-prompt-corto-banco306.json   THE FINE-TUNE  -> this is the question
  resultado_4b-banco-completo-repuntuado.json        stock 4B, LONG prompt -> 282/306 = 92.2 %

The point of the fine-tune is to pull the short-prompt number up towards the long-prompt
one, WITHOUT paying the 11,881 characters. So the verdict is not "did it improve" but
"how much of the 16.7-point gap did it close".

It reports overall, per block, and lists exactly which cases flipped — because a single
aggregate number hides whether an improvement is broad or a handful of lucky cases.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def cargar(nombre):
    ruta = os.path.join(BASE, nombre)
    if not os.path.exists(ruta):
        print("  FALTA: %s" % nombre)
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def aciertos(datos):
    """Returns {(caso, idioma): ok} from a harness result file.

    The harness writes `_ok` (verified by dumping a row: the keys are herramienta,
    argumentos, _encontrados, prohibido, _bloqueados, seguridad, _ok, ...). An earlier
    version of this function looked for `ok`/`correcto` and reported a flat 0 % for every
    file -- the reader was wrong, not the model.
    """
    if not datos:
        return {}
    salida = {}
    for fila in datos.get("filas", []):
        salida[(fila.get("caso"), fila.get("idioma"))] = bool(fila.get("_ok"))
    return salida


def bloque(caso):
    """The case id is prefixed by its block: paq-x, escri-x, trampa-x..."""
    return caso.split("-")[0] if caso else "?"


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


def main():
    stock_corto = cargar("resultado_4b-prompt-corto-banco306.json")
    finetune = cargar("resultado_4b-finetune-prompt-corto-banco306.json")
    stock_largo = cargar("resultado_4b-banco-completo-repuntuado.json")

    if not finetune:
        print("Todavia no hay resultado del fine-tune. Nada que comparar.")
        return

    fs = aciertos(finetune)
    ss = aciertos(stock_corto) if stock_corto else {}
    ls = aciertos(stock_largo) if stock_largo else {}

    n = len(fs)
    ok_f = sum(1 for v in fs.values() if v)
    print("=" * 82)
    print("EL 4B ENTRENADO, medido con el prompt CORTO (214 caracteres)")
    print("=" * 82)
    print()
    if ss:
        ok_s = sum(1 for k, v in ss.items() if v and k in fs)
        cmp_s = sum(1 for k in fs if k in ss)
        print("  referencia  SIN entrenar, prompt corto : %3d/%3d = %.1f %%"
              % (ok_s, cmp_s, pct(ok_s, cmp_s)))
    print("  ESTE        ENTRENADO,  prompt corto   : %3d/%3d = %.1f %%"
          % (ok_f, n, pct(ok_f, n)))
    if ls:
        ok_l = sum(1 for k, v in ls.items() if v and k in fs)
        cmp_l = sum(1 for k in fs if k in ls)
        print("  techo       SIN entrenar, prompt LARGO : %3d/%3d = %.1f %%  (11.881 car.)"
              % (ok_l, cmp_l, pct(ok_l, cmp_l)))
    print()

    if ss:
        comunes = [k for k in fs if k in ss]
        gana = sum(1 for k in comunes if fs[k] and not ss[k])
        pierde = sum(1 for k in comunes if ss[k] and not fs[k])
        dif = pct(sum(1 for k in comunes if fs[k]), len(comunes)) - \
            pct(sum(1 for k in comunes if ss[k]), len(comunes))
        print("  --- frente a la referencia de prompt corto ---")
        print("      MEJORA : %+5.1f puntos   (%d casos que ahora acierta)" % (dif, gana))
        print("      PIERDE : %d casos que antes acertaba y ahora no" % pierde)
        print()
        if ls:
            base_l = pct(sum(1 for k in comunes if ls.get(k)), len(comunes))
            base_s = pct(sum(1 for k in comunes if ss[k]), len(comunes))
            hecho = pct(sum(1 for k in comunes if fs[k]), len(comunes))
            hueco = base_l - base_s
            cerrado = (hecho - base_s) / hueco * 100 if hueco else 0
            print("  --- cuanto del hueco se ha cerrado ---")
            print("      sin entrenar (corto) : %.1f %%" % base_s)
            print("      entrenado            : %.1f %%" % hecho)
            print("      techo (prompt largo) : %.1f %%" % base_l)
            print("      HUECO CERRADO        : %.0f %% de los %.1f puntos" % (cerrado, hueco))
            print()

    print("  --- por bloque (aciertos sobre el total del bloque) ---")
    bloques = sorted({bloque(k[0]) for k in fs})
    print("      %-12s %6s %6s %6s" % ("bloque", "corto", "entren", "largo"))
    for b in bloques:
        claves = [k for k in fs if bloque(k[0]) == b]
        c = pct(sum(1 for k in claves if ss.get(k)), len(claves)) if ss else 0
        e = pct(sum(1 for k in claves if fs[k]), len(claves))
        l = pct(sum(1 for k in claves if ls.get(k)), len(claves)) if ls else 0
        print("      %-12s %5.0f%% %5.0f%% %5.0f%%" % (b, c, e, l))
    print()

    if ss:
        comunes = [k for k in fs if k in ss]
        ganados = sorted(k for k in comunes if fs[k] and not ss[k])
        perdidos = sorted(k for k in comunes if ss[k] and not fs[k])
        print("  --- casos que AHORA acierta y antes no (%d) ---" % len(ganados))
        for c, i in ganados:
            print("      %-34s %s" % (c, i))
        print()
        print("  --- casos que HA PERDIDO (%d) ---" % len(perdidos))
        for c, i in perdidos:
            print("      %-34s %s" % (c, i))
    print()
    print("=" * 82)


if __name__ == "__main__":
    main()
