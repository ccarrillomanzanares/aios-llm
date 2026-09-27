#!/usr/bin/env python3
"""Adds the last two uncovered tools: torrent_search and torrent_download.

Why they were missing matters: the counting found them, not a hunch. `torrent_*`
looked covered because three of the five had a trap case, and the two that carry
the actual user-facing flow ("find me something to watch, download it") were the
ones without any. A group that scores well because only part of it is measured
isn't measured, and that is the exact way this bench has lied before.

Run once, from bateria/. Refuses to run twice.
"""
import collections
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE, "casos.json")

NUEVOS = [
    {
        "id": "torrent-buscar", "grupo": "red", "tipo": "lectura",
        "esperado": {"herramienta": "torrent_search", "patron": "Metropolis"},
        "prohibido": ["apibay.org/q.php", "curl -s", "wget"],
        "comprobacion": {"herramienta": "torrent_search",
                         "args": {"query": "Metropolis 1927 Fritz Lang", "limit": 2},
                         "contiene": "results"},
        "por_que": "The entry point of the whole media flow, and the tool the prompt is most emphatic about: 'ALWAYS use this to find something to watch or download -- never invent names or links'. The oracle really has internet, so the search really returns results, and the check above proves it. Going around the tool with curl against the indexer is forbidden: that is how a model ends up inventing a magnet link.",
        "idiomas": {
            "en": "I want to watch Fritz Lang's Metropolis from 1927. Find it for me.",
            "es": "Quiero ver Metrópolis de Fritz Lang, la de 1927. Búscamela.",
            "fr": "Je veux voir Metropolis de Fritz Lang, celui de 1927. Trouve-le-moi.",
            "de": "Ich möchte Fritz Langs Metropolis von 1927 sehen. Finde ihn für mich.",
            "it": "Voglio vedere Metropolis di Fritz Lang, quello del 1927. Trovalo per me.",
            "pt": "Quero ver Metropolis do Fritz Lang, de 1927. Procura-mo.",
        },
    },
    {
        "id": "torrent-bajar", "grupo": "red", "tipo": "mutante",
        "esperado": {"herramienta": "torrent_download",
                     "patron": "\"target\"\\s*:\\s*\"?(1|2|magnet)"},
        "prohibido": ["apibay.org/q.php", "aria2c http"],
        "por_que": "The second half of the flow, and the one that has to be multi-step: the number only means something after a search, so a model that downloads '1' without searching first is downloading someone else's guess. The oracle has no transmission daemon, so the tool answers with its real 'RPC unreachable' error -- and that is fine: what is scored is that the right tool was called with a sensible target, and the honest reporting of the error is visible in the trajectory.",
        "idiomas": {
            "en": "Find Metropolis by Fritz Lang and start downloading the first result.",
            "es": "Busca Metrópolis de Fritz Lang y empieza a descargar el primer resultado.",
            "fr": "Trouve Metropolis de Fritz Lang et commence à télécharger le premier résultat.",
            "de": "Finde Metropolis von Fritz Lang und lade das erste Ergebnis herunter.",
            "it": "Trova Metropolis di Fritz Lang e inizia a scaricare il primo risultato.",
            "pt": "Procura Metropolis do Fritz Lang e começa a descarregar o primeiro resultado.",
        },
    },
]


def main():
    banco = json.load(open(RUTA, encoding="utf-8"))
    ids = {c["id"] for c in banco["casos"]}
    ya = [c["id"] for c in NUEVOS if c["id"] in ids]
    if ya:
        print("already present: %s -- refusing to add them twice." % ", ".join(ya))
        return 1
    for c in NUEVOS:
        faltan = [k for k in banco["idiomas"] if k not in c["idiomas"]]
        assert not faltan, "%s is missing languages: %s" % (c["id"], faltan)
    banco["casos"].extend(NUEVOS)
    json.dump(banco, open(RUTA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    cub, tools = set(), [t["function"]["name"] for t in
                         json.load(open(os.path.join(BASE, "tools.json"), encoding="utf-8"))]
    for c in banco["casos"]:
        e = c.get("esperado") or {}
        if e.get("herramienta"):
            cub.add(e["herramienta"])
        for a in (e.get("alternativas") or []):
            if a.get("herramienta"):
                cub.add(a["herramienta"])
    faltan = [t for t in tools if t not in cub]
    print("total cases      : %d  (= %d evaluations across %d languages)"
          % (len(banco["casos"]), len(banco["casos"]) * len(banco["idiomas"]), len(banco["idiomas"])))
    print("by group         : %s" % dict(collections.Counter(c["grupo"] for c in banco["casos"])))
    print("by type          : %s" % dict(collections.Counter(c["tipo"] for c in banco["casos"])))
    print("with comprobacion: %d" % sum(1 for c in banco["casos"] if c.get("comprobacion")))
    print("tools covered    : %d/%d" % (len(cub), len(tools)))
    print("tools WITHOUT a case: %s" % (faltan or "none"))
    return 0 if not faltan else 2


if __name__ == "__main__":
    sys.exit(main())
