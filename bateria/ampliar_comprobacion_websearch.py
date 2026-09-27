#!/usr/bin/env python3
"""Gives `red-buscar` (web_search) a real `comprobacion` now that Firecrawl runs.

Why it was not there before: the oracle could not reach Firecrawl, so the case
could only score which tool the model picked. With the service up and the oracle's
loopback bridged to the VPS's, the tool can be run and its answer compared — which
turns the case from "it chose web_search" into "web_search really returned results".

Run once, from bateria/. Refuses to run twice.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE, "casos.json")

COMPROBACION = {
    "herramienta": "web_search",
    "args": {"query": "ultima version del kernel linux", "limit": 2},
    "contiene": "results",
}
POR_QUE_EXTRA = (" And measured on 27 sep: the oracle now REACHES Firecrawl (installed in Docker at "
                 "/opt/firecrawl), so the tool is actually run and its answer compared. What it does "
                 "NOT require is a true fact — an indexer's answer varies with time, so what is "
                 "checked is that real results came back, not which kernel is newest.")


def main():
    banco = json.load(open(RUTA, encoding="utf-8"))
    tocado = False
    for c in banco["casos"]:
        if c["id"] != "red-buscar":
            continue
        if c.get("comprobacion"):
            print("red-buscar already has a comprobacion")
            return 0
        c["comprobacion"] = COMPROBACION
        if POR_QUE_EXTRA.strip() not in c.get("por_que", ""):
            c["por_que"] = (c.get("por_que", "").rstrip() + POR_QUE_EXTRA)
        tocado = True
    if not tocado:
        print("case red-buscar not found")
        return 1
    json.dump(banco, open(RUTA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    con = sum(1 for c in banco["casos"] if c.get("comprobacion"))
    print("red-buscar now exercises web_search for real")
    print("cases with comprobacion: %d of %d" % (con, len(banco["casos"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
