#!/usr/bin/env python3
"""Count how many of the 29 production tools the bench actually exercises.

WHY THIS IS A SCRIPT AND NOT A SENTENCE. The plan asserts "29/29 tools covered" and the
project's own rule is that nothing is taken as good without a measurement -- but this
claim had no script behind it, so it could not be reproduced or checked. It was also
easy to get wrong: the first attempt at counting (28 sep) only looked at
`esperado.herramienta` and missed the tools named inside `esperado.alternativas`, which
is how `get_installed_info` is declared in `paq-listar` and `diag-paquetes-cuantos`.
That version reported 27/29 and "two tools with no case"; the second of them
(`torrent_search`) did have a case. A count that is wrong in the direction of accusing
the bench of a gap is as bad as one that hides it.

WHAT IT LOOKS AT, exhaustively: every field of a case that can name a tool --
  esperado.herramienta, esperado.alternativas[].herramienta,
  comprobacion.herramienta, and any other top-level "*herramienta*" key.
The tool registry it compares against is the PRODUCTION one (`tools.json`), not a list
typed in a document.

Usage:
    python3 cobertura_herramientas.py            # the count
    python3 cobertura_herramientas.py --sin-holdout  # only what generates material
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def casos_del_registro():
    """The real production registry. If `tools.json` is a wrapper, unwrap it."""
    d = json.load(open(os.path.join(BASE, "tools.json"), encoding="utf-8"))
    if isinstance(d, dict) and "tools" not in d and "herramientas" not in d:
        d = list(d.values())[0]
    if isinstance(d, dict):
        d = d.get("tools") or d.get("herramientas")
    nombres = []
    for t in d:
        f = t.get("function", t)
        n = f.get("name")
        if n:
            nombres.append(n)
    return nombres


def herramientas_de(caso):
    """Every tool this case can legitimately name, wherever it says it."""
    h = set()

    def mira(v):
        if isinstance(v, dict):
            if v.get("herramienta"):
                h.add(v["herramienta"])
            for x in v.values():
                mira(x)
        elif isinstance(v, list):
            for x in v:
                mira(x)

    for k, v in caso.items():
        if "herramienta" in k.lower() or k in ("esperado", "comprobacion", "alternativas"):
            mira(v)
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-holdout", action="store_true",
                    help="count only the cases that generate training material")
    args = ap.parse_args()

    registro = casos_del_registro()
    casos = json.load(open(os.path.join(BASE, "casos.json"), encoding="utf-8"))["casos"]
    ruta_h = os.path.join(BASE, "holdout.txt")
    reserv = set()
    if os.path.isfile(ruta_h):
        reserv = {l.split("#")[0].strip() for l in open(ruta_h, encoding="utf-8")
                  if l.split("#")[0].strip()}

    ejercidas = set()
    por_herramienta = {}
    de_generadores = set()
    de_reservados = set()
    for c in casos:
        hs = herramientas_de(c)
        for x in hs:
            por_herramienta.setdefault(x, []).append(c["id"])
        if args.sin_holdout:
            # The union of the generating cases, computed separately from the reserved
            # ones. The FIRST version of this flag subtracted every tool that appeared
            # in a reserved case, even when a generating case used it too, and so
            # reported `run_command` and `read_file` as uncovered -- absurd on its face,
            # since they are the most used tools in the material. What matters is only
            # the tool that lives EXCLUSIVELY in the reserved set: that is the one that
            # can never be learnt.
            (de_reservados if c["id"] in reserv else de_generadores).update(hs)
        ejercidas.update(hs)
    if args.sin_holdout:
        ejercidas = de_generadores

    print("registry (tools.json)          : %d tools" % len(registro))
    print("cases                          : %d (%d reserved, %d generate material)"
          % (len(casos), len(reserv), len(casos) - len(reserv)))
    if args.sin_holdout:
        print("counting only the ones that GENERATE material")
        print("  tools of the generating cases : %d" % len(de_generadores))
        print("  tools ONLY in reserved cases  : %s"
              % (", ".join(sorted(de_reservados - de_generadores)) or "none"))
    print()
    cubiertas = [t for t in registro if t in ejercidas]
    sin_caso = [t for t in registro if t not in ejercidas]
    print("COVERED  : %d / %d" % (len(cubiertas), len(registro)))
    print("NOT COVERED: %s" % (", ".join(sin_caso) if sin_caso else "none"))
    print()
    fuera = [t for t in ejercidas if t not in registro]
    if fuera:
        print("AVISO: cases name tools that are NOT in the registry: %s" % ", ".join(sorted(fuera)))
        print("       (a case testing a tool that does not exist proves nothing)")
        print()
    print("how many cases exercise each tool:")
    for t in sorted(registro):
        n = len(por_herramienta.get(t, []))
        marca = "" if n else "   <-- NO CASE"
        print("   %-22s %d%s" % (t, n, marca))
    return 0


if __name__ == "__main__":
    sys.exit(main())
