#!/usr/bin/env python3
"""Re-puntua una corrida YA HECHA del banco multi-paso, sin volver a ejecutarla.

Para que sirve: cuando el fallo de un caso es del INSTRUMENTO (un patron que
caza de mas, una forma valida que el caso no contemplaba), no hay que gastar 2
horas de GPU ni de oraculo. Las trayectorias guardadas tienen las llamadas del
modelo tal cual las hizo; se vuelven a puntuar con el casos.json corregido y el
numero se actualiza solo.

Lo que NO re-puntua, y hay que decirlo en voz alta: `comprobar_final` (las
tareas que se verifican en el ESTADO FINAL del oraculo). Ese dato se mide
ejecutando y se reaprovecha tal cual del resultado original.

Uso:
    sudo python3 repuntuar.py --casos casos.json.v1     # control: debe reproducir el numero viejo
    sudo python3 repuntuar.py                           # con el casos.json corregido
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ejecutor  # noqa: E402
from bateria_agente import puntuar  # noqa: E402


def llamadas_de(mensajes):
    """Reconstruye las llamadas de una trayectoria, igual que hizo `evaluar`."""
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
    args = ap.parse_args()

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
            # error de red (sin trayectoria) o caso retirado: se arrastra tal cual
            sin_tray.append(k)
            nuevas.append(dict(f))
            continue
        p = puntuar(caso, llamadas_de(tray[k]["mensajes"]), f.get("texto_final", ""), capa)
        for campo in ("pasos", "segundos", "texto_final", "herramienta_usada", "error",
                      "tarea_ok", "caso", "grupo", "idioma", "tipo"):
            if campo in f:
                p[campo] = f[campo]
        p["_ok"] = p["_ok"] and (f.get("tarea_ok") is not False)
        if bool(p["_ok"]) != bool(f.get("_ok")):
            cambios.append((k, bool(f.get("_ok")), bool(p["_ok"]), p.get("_encontrados")))
        nuevas.append(p)

    ok = sum(1 for x in nuevas if x.get("_ok"))
    total = len(nuevas)
    print("=" * 96)
    print("RE-PUNTUADO con %s" % args.casos)
    print("=" * 96)
    print("RESULTADO: %d/%d = %.1f%%" % (ok, total, 100.0 * ok / max(1, total)))
    print("(sin trayectoria, arrastradas tal cual: %d -> %s)"
          % (len(sin_tray), ", ".join("%s/%s" % k for k in sin_tray) or "ninguna"))

    if cambios:
        print("\nCAMBIOS:")
        for k, antes, ahora, enc in cambios:
            print("  %-28s %-3s  %s -> %s   %s" % (k[0], k[1], "OK" if antes else "FALLA",
                                                   "OK" if ahora else "FALLA",
                                                   ("prohibido encontrado: %s" % enc) if enc else ""))

    trampas = [x for x in nuevas if x.get("tipo") == "trampa"]
    to = sum(1 for x in trampas if x.get("_ok"))
    print("\nTRAMPAS DE SEGURIDAD: %d/%d" % (to, len(trampas)))
    for x in trampas:
        if not x.get("_ok"):
            print("   FALLA %-26s %-3s usado=%s" % (x["caso"], x["idioma"],
                                                    x.get("herramienta_usada", "?")))
    for agrup in ("grupo", "idioma"):
        print("\nPOR %s" % agrup.upper())
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
    print("\ndetalle: %s" % salida)


if __name__ == "__main__":
    main()