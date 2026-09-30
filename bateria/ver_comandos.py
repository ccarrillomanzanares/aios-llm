#!/usr/bin/env python3
"""Print the ACTUAL COMMANDS the fine-tune ran, for the cases that failed on a trap.

Why this exists: the bench flags a case when a forbidden string appears anywhere in the
trajectory. That cannot tell "I ran apt-get update" from "apt-get is not installed on this
system, the manager here is sven". The German case says literally the second thing, and
scoring it as a violation would be the instrument's error, not the model's.

The `mensajes` field records every tool call with its arguments, so the real commands can be
printed and read. Same rule the bench itself already applies with its {"regex": ...} escape
hatch: a bare substring must never be the final word.

Usage: ver_comandos.py <trayectorias.jsonl> <caso> [caso ...]
"""
import json
import sys


def comandos_de(traj):
    """Every tool call in the trajectory, as (nombre, argumentos)."""
    salida = []
    for m in traj.get("mensajes", []):
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function", {})
            salida.append((fn.get("name"), fn.get("arguments")))
    return salida


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    ruta = sys.argv[1]
    quiero = set(sys.argv[2:])

    with open(ruta, encoding="utf-8") as f:
        trajs = [json.loads(l) for l in f if l.strip()]

    for t in trajs:
        caso = t.get("caso")
        if caso not in quiero:
            continue
        print("=" * 94)
        print("### %s [%s]   peticion: %s" % (caso, t.get("idioma"),
                                              (t.get("peticion") or "")[:90]))
        cmds = comandos_de(t)
        if not cmds:
            print("   (no llamo a ninguna herramienta)")
        for i, (nom, args) in enumerate(cmds, 1):
            print("   %2d. %s" % (i, nom))
            if args:
                try:
                    d = json.loads(args) if isinstance(args, str) else args
                    for k, v in d.items():
                        print("        %s = %s" % (k, str(v)[:400]))
                except Exception:
                    print("        %s" % str(args)[:400])
        # The final assistant text, which is where a refusal or a confession lives.
        for m in reversed(t.get("mensajes", [])):
            if m.get("role") == "assistant" and (m.get("content") or "").strip():
                print("   --- respuesta final:")
                for linea in m["content"].strip()[:700].splitlines():
                    print("       | %s" % linea)
                break
        print()


if __name__ == "__main__":
    main()
