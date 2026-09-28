#!/usr/bin/env python3
"""Re-scores an ALREADY DONE run of the multi-step bench, without running it again.

What it is for: when a case's failure is the INSTRUMENT's fault (a pattern that
over-catches, a valid form the case did not contemplate), there is no need to spend
2 hours of GPU or oracle. The saved trajectories hold the model's calls exactly as it
made them; they are scored again with the corrected casos.json and the
number updates itself.

What it does NOT re-score, and this has to be said out loud: `comprobar_final` (the
tasks that are verified in the FINAL STATE of the oracle). That datum is measured
by executing and is reused as is from the original result.

Usage:
    sudo python3 repuntuar.py --casos casos.json.v1     # control: it must reproduce the old number
    sudo python3 repuntuar.py                           # with the corrected casos.json
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ejecutor  # noqa: E402
from bateria_agente import puntuar  # noqa: E402
from revisar_respuesta import revisar, texto_final  # noqa: E402


def llamadas_de(mensajes):
    """Rebuilds the calls of a trajectory, just as `evaluar` did."""
    llamadas = []
    for m in mensajes:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                f = tc.get("function", {})
                try:
                    a = json.loads(f.get("arguments") or "{}")
                except Exception:
                    a = {"_crudo": f.get("arguments")}
                llamadas.append({"nombre": f.get("name", ""), "args": a})
    return llamadas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etiqueta", default="35b-multipaso")
    ap.add_argument("--casos", default="casos.json")
    ap.add_argument("--json-salida", default=None)
    ap.add_argument("--forzar", action="store_true",
                    help="allow overwriting an existing re-scored result")
    args = ap.parse_args()

    salida = args.json_salida or os.path.join(BASE, "resultado_%s-repuntuado.json" % args.etiqueta)
    # This file holds a MEASURED NUMBER the project uses as its baseline, and the
    # default output name is the same one. It has already been clobbered once: the
    # mandatory control run (`--casos casos.json.v1`) overwrote the 172/174 baseline
    # with 167/174, which is a CORRECT number for the old bench and a false one for
    # this file. Refusing by default, saying which, and offering --forzar.
    if os.path.isfile(salida) and not args.forzar and args.json_salida is None:
        print("REFUSING to overwrite %s" % salida)
        print("It holds a measured number that this project uses as a baseline.")
        print("Pass --json-salida FILE to write elsewhere, or --forzar to replace it.")
        return 1

    casos = json.load(open(os.path.join(BASE, args.casos), encoding="utf-8"))["casos"]
    por_id = {c["id"]: c for c in casos}
    filas = json.load(open(os.path.join(BASE, "resultado_%s.json" % args.etiqueta),
                           encoding="utf-8"))["filas"]
    tray = {}
    with open(os.path.join(BASE, "trayectorias_%s.jsonl" % args.etiqueta), encoding="utf-8") as f:
        for linea in f:
            j = json.loads(linea)
            tray[(j["caso"], j["idioma"])] = j

    capa = ejecutor._capa()
    nuevas, sin_tray, cambios = [], [], []
    for f in filas:
        k = (f["caso"], f["idioma"])
        caso = por_id.get(f["caso"])
        if caso is None or k not in tray:
            # network error (no trajectory) or withdrawn case: carried over as is
            sin_tray.append(k)
            nuevas.append(dict(f))
            continue
        p = puntuar(caso, llamadas_de(tray[k]["mensajes"]), f.get("texto_final", ""), capa)
        # The closing answer, from the trajectory and not from the row: the row is
        # truncated to 300 chars and the number being looked for can fall past it.
        r_ok = revisar(caso, texto_final(tray[k]["mensajes"]))
        p["respuesta_ok"] = r_ok
        for campo in ("pasos", "segundos", "texto_final", "herramienta_usada", "error",
                      "tarea_ok", "caso", "grupo", "idioma", "tipo"):
            if campo in f:
                p[campo] = f[campo]
        p["_ok"] = (p["_ok"] and (f.get("tarea_ok") is not False)
                    and (f.get("comprobacion_ok") is not False) and (r_ok is not False))
        if bool(p["_ok"]) != bool(f.get("_ok")):
            cambios.append((k, bool(f.get("_ok")), bool(p["_ok"]), p.get("_encontrados")))
        nuevas.append(p)

    ok = sum(1 for x in nuevas if x.get("_ok"))
    total = len(nuevas)
    print("=" * 96)
    print("RE-SCORED with %s" % args.casos)
    print("=" * 96)
    print("RESULT: %d/%d = %.1f%%" % (ok, total, 100.0 * ok / max(1, total)))
    print("(no trajectory, carried over as is: %d -> %s)"
          % (len(sin_tray), ", ".join("%s/%s" % k for k in sin_tray) or "none"))

    if cambios:
        print("\nCHANGES:")
        for k, antes, ahora, enc in cambios:
            print("  %-28s %-3s  %s -> %s   %s" % (k[0], k[1], "OK" if antes else "FAIL",
                                                   "OK" if ahora else "FAIL",
                                                   ("forbidden found: %s" % enc) if enc else ""))

    trampas = [x for x in nuevas if x.get("tipo") == "trampa"]
    to = sum(1 for x in trampas if x.get("_ok"))
    print("\nSECURITY TRAPS: %d/%d" % (to, len(trampas)))
    for x in trampas:
        if not x.get("_ok"):
            print("   FAIL  %-26s %-3s used=%s" % (x["caso"], x["idioma"],
                                                    x.get("herramienta_usada", "?")))
    for agrup in ("grupo", "idioma"):
        print("\nBY %s" % agrup.upper())
        g = {}
        for x in nuevas:
            g.setdefault(x.get(agrup, "?"), []).append(x)
        for kk in sorted(g):
            v = g[kk]
            print("   %-16s %2d/%2d  %3.0f%%" % (kk, sum(1 for x in v if x.get("_ok")), len(v),
                                                 100.0 * sum(1 for x in v if x.get("_ok")) / len(v)))

    salida = args.json_salida or os.path.join(BASE, "resultado_%s-repuntuado.json" % args.etiqueta)
    json.dump({"etiqueta": args.etiqueta, "casos": args.casos, "filas": nuevas},
              open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\ndetails: %s" % salida)


if __name__ == "__main__":
    main()