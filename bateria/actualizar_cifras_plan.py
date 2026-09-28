#!/usr/bin/env python3
"""Replace the loose superseded figures in PLAN-MAESTRO.md, once and for all.

Each replacement has to match EXACTLY ONE line. If a pattern matches zero lines it is
reported as not found (the plan moved on and the entry is obsolete); if it matches more
than one, the script stops without writing anything, because a blind replace across a
document is how two figures for the same thing end up coexisting -- the exact problem
this whole exercise is fixing.
"""
import os
import sys

PLAN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "PLAN-MAESTRO.md")

# (old fragment, new fragment, why)
CAMBIOS = [
    ("**encoger el prompt**. La composición del dataset pasa de estimación",
     "**encoger el prompt, sin perder lo que ya hace bien** (§3.1b). La composición del dataset pasa de estimación",
     "los dos objetivos, no uno"),
    ("La puerta A/B se reformula: «superar al 35B» deja de ser un criterio útil con 172/174 (§8.6)",
     "La puerta A/B se reformula: «superar al 35B» deja de ser un criterio útil con el 35B casi en el techo (§8.6)",
     "no citar el numero viejo en el resumen"),

    ("> **2,74 GB**, corre en CPU sin GPU, y da **93,1 %** en el banco. La duda ya no es «qué talla",
     "> **2,74 GB**, corre en CPU sin GPU, y da el **92,2 %** en el banco (§3.1). La duda ya no es «qué talla",
     "la cifra de hoy"),

    ("Esta sección medía contra el banco de **174 evaluaciones**.",
     "Esta sección medía contra el banco viejo de 174 evaluaciones.",
     "queda claro que es historia, no la vara de hoy"),

    ("**29 casos × 6 idiomas = 174 evaluaciones.** Construido, funcionando y **corregido 9 veces**",
     "**51 casos × 6 idiomas = 306 evaluaciones.** Construido, funcionando y **corregido 22 veces**",
     "el banco crecio"),

    ("banco viejo el re-puntuador tiene que reproducir el número exacto: dio 154/174 y 172/174, sin",
     "banco viejo el re-puntuador reproduce el número exacto del banco viejo, sin",
     "no soltar las cifras viejas sueltas: basta decir que el control cuadra"),

    ("53/54) y su control sigue dando 167/174 con `casos.json.v1`.",
     "y su control sigue cuadrando con `casos.json.v1` (el banco viejo).",
     "idem"),

    ("> Con el banco medido, el 35B está en **172/174 = 98,9 %** — a **dos fallos del techo**. «Superar»",
     "> Con el banco medido, el 35B está casi en el techo — a **cuatro fallos**. «Superar»",
     "cifra de hoy, sin citar la vieja"),

    ("> Y el 4B con andamio persigue cerca (93,1 %) siendo **más rápido** (29,7 s frente a 39,6 s).",
     "> Y el 4B con andamio persigue cerca (92,2 %) y **es más rápido en CPU** que el 35B.",
     "cifra de hoy"),

    ("| **No-regresión** | Con el prompt de producción **no baja del 93,1 %** | El modelo nuevo no sustituye a nada |",
     "| **No-regresión** | Con el prompt de producción **no baja del 92,2 %** | El modelo nuevo no sustituye a nada |",
     "cifra de hoy"),

    ("**51 casos × 6 idiomas = 306 evaluaciones**, con el prompt y los esquemas reales de producción). Análisis de lo reutilizable (§6.5a), selección **medida** del profesor (§6.5b). **Sin GPU**, más lo medido el 27 sep: **el 4B en 4 configuraciones (§3.1)** — 93,1 % / 88,5 % / 72,4 %, y el 35B en 98,9 % | La batería corre y da un número. **Línea base medida del 4B, que el plan no tenía.** Profesor elegido con datos.",
     "**51 casos × 6 idiomas = 306 evaluaciones** con **29/29** herramientas, con el prompt y los esquemas reales de producción). Análisis de lo reutilizable (§6.5a), selección **medida** del profesor (§6.5b). **Sin GPU**, más las medidas del 28 sep: **el 4B en 92,2 % y el 35B en 98,7 % (§3.1)**, y el 4B sin andamio en 72,4 % (banco viejo) | La batería corre y da un número. **Línea base medida del 4B, que el plan no tenía.** Profesor elegido con datos.",
     "la fase 0 con los numeros de hoy"),

    ("**Medido: con el andamio ya retiene el 93,1 %** (§3.1). El riesgo se reduce a su hueco real: paquetes, diagnóstico y trampas.",
     "**Medido: con el andamio ya retiene el 92,2 %** (§3.1). El riesgo se reduce a su hueco real, que la tabla de §6.3 mide bloque a bloque.",
     "cifra de hoy"),

    ("La puerta de no-regresión (§8.6): con el prompt de producción no puede bajar del 93,1 % |",
     "La puerta de no-regresión (§8.6): con el prompt de producción no puede bajar del 92,2 % |",
     "cifra de hoy"),

    ("| 10 | **El pensamiento se queda encendido** | ✅ Medido: apagarlo baja los aciertos (93,1→88,5 %) y sube el tiempo (29,7→49,1 s) | **cerrado** |",
     "| 10 | **El pensamiento se queda encendido** | ✅ Medido con el banco viejo: apagarlo baja los aciertos y sube el tiempo. **Falta re-medirlo con el banco de 306** antes de darlo por cerrado del todo | **cerrado con reserva** |",
     "no soltar cifras del banco viejo"),

    ("| 11 | **La puerta A/B se mide sobre el prompt corto** (§8.6) | ✅ «Superar al 35B» no es medible con 172/174 | **cerrado** |",
     "| 11 | **La puerta A/B se mide sobre el prompt corto** (§8.6) | ✅ «Superar al 35B» no es un criterio medible con el profesor casi en el techo | **cerrado** |",
     "idem"),
]


def main():
    texto = open(PLAN, encoding="utf-8").read()
    original = texto
    hechos, no_encontrados, ambiguos = 0, [], []
    # Apply on the whole text but demand a single occurrence inside the file.
    for viejo, nuevo, porque in CAMBIOS:
        n = texto.count(viejo)
        if n == 0:
            no_encontrados.append(viejo[:70])
            continue
        if n > 1:
            ambiguos.append((n, viejo[:70]))
            continue
        texto = texto.replace(viejo, nuevo)
        hechos += 1
        print("  OK   %s" % porque)

    for t in no_encontrados:
        print("  NO ENCONTRADO: %s" % t)
    for n, t in ambiguos:
        print("  AMBIGUO (%d veces), NO se toca: %s" % (n, t))

    if ambiguos:
        print("\nNo escribo nada: hay patrones ambiguos.")
        return 1
    if texto != original:
        open(PLAN, "w", encoding="utf-8").write(texto)
        print("\nplan escrito: %d cambios" % hechos)
    else:
        print("\nsin cambios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
