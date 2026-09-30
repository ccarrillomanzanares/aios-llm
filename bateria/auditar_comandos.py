#!/usr/bin/env python3
"""Did the forbidden commands actually RUN, or were they only mentioned?

This is the distinction the whole verdict turns on. The bench marks a case forbidden when a
string appears; it cannot tell a command that was EXECUTED from one that was named in a
sentence like "apt is not installed here, you use sven". The German case reads exactly like
that second thing.

So this reads the training trajectories, which record every tool call WITH its arguments,
and prints the actual commands for the cases that failed. Same discipline as the bench's own
{"regex": ...} escape hatch: never let a bare substring decide.

Usage: auditar_comandos.py <trayectorias.jsonl> [caso ...]
"""
import json
import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    ruta = sys.argv[1]
    filtro = set(sys.argv[2:])

    filas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                filas.append(json.loads(linea))

    for r in filas:
        caso = r.get("caso")
        if filtro and caso not in filtro:
            continue
        if not caso or not caso.startswith("trampa"):
            continue
        idi = r.get("idioma")
        print("=" * 92)
        print("### %s [%s]" % (caso, idi))
        # The trajectory records the steps; print each tool call and its arguments.
        pasos = r.get("pasos") or r.get("turnos") or r.get("steps") or []
        if not pasos:
            # Fall back to any list of steps under another key.
            for k, v in r.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    pasos = v
                    print("      (usando la clave '%s' para los pasos)" % k)
                    break
        for i, p in enumerate(pasos, 1):
            if not isinstance(p, dict):
                continue
            nombre = p.get("herramienta") or p.get("tool") or p.get("nombre") or p.get("name")
            args = p.get("argumentos") or p.get("arguments") or p.get("args")
            if nombre or args:
                print("  paso %d: %s" % (i, nombre))
                txt = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
                for linea in str(txt)[:500].splitlines() or [""]:
                    print("      %s" % linea)
        print()


if __name__ == "__main__":
    main()
