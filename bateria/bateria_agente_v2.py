#!/usr/bin/env python3
"""MULTI-STEP bench of aios-llm — v2, running the agent's SHIPPED code.

Difference from `bateria_agente.py` (kept untouched, because it produced the
baseline the whole project is measured against: 35B 173/174, traps 53/54):

  1. It uses `ejecutor_v2`, which calls `tools.execute_tool()` INSIDE the oracle
     instead of translating tools into shell commands. What the model receives is
     what a user would receive.

  2. It supports `comprobacion`, the strongest check in the bench: the case names
     a tool and arguments, the bench calls that tool in the oracle, and compares
     the real output against the expected text. A hallucinated answer cannot pass.

  3. A failed `comprobacion` is reported as an INSTRUMENT failure, not a model
     failure, and the case is excluded from the score. If the environment cannot
     run the tool, there is no measurement to make — saying "the model failed"
     there is the exact mistake this project has already made nine times.

Usage:
    sudo python3 bateria_agente_v2.py --limite 3 --idioma es
    sudo python3 bateria_agente_v2.py --solo torrent-,nave- --etiqueta prueba

It goes with sudo because the oracle mounts with privileges.
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ejecutor_v2 as ejecutor          # noqa: E402  the one that runs shipped code
from bateria_agente import puntuar, leer_clave_api, preguntar, MAX_TURNOS  # noqa: E402
from revisar_respuesta import revisar, detalle  # noqa: E402  checks the CLOSING ANSWER


def _cargar(nombre):
    return json.load(open(os.path.join(BASE, nombre), encoding="utf-8"))


def comprobar(caso, capa):
    """Runs the case's own tool and checks the real output. Returns (ok, detalle)."""
    c = caso.get("comprobacion")
    if not c:
        return None, ""
    salida = ejecutor.ejecutar(c["herramienta"], c.get("args") or {})
    esperado = c.get("contiene")
    if esperado is None:
        return bool(salida.strip()) and "\"error\"" not in salida, salida[:200]
    ok = esperado in salida
    return ok, ("esperaba %r en %s" % (esperado, salida[:220]))


def _necesita_navegador(caso):
    """True if this case expects a browser_* tool.

    The bench has to provide the browser, and it has to do it per case: chromium
    cannot be started by the agent itself (it runs as root and Chromium refuses to
    run as root without --no-sandbox), its profile lives in /tmp, and the reset
    replaces /tmp's tmpfs. So it is started before the conversation and it dies
    with the reset, which is the correct lifetime for throwaway infrastructure.
    """
    e = caso.get("esperado") or {}
    nombres = [e.get("herramienta")] + [a.get("herramienta") for a in (e.get("alternativas") or [])]
    return any((n or "").startswith("browser_") for n in nombres)


def evaluar(caso, idioma, texto, args, prompt, tools, capa, clave):
    """One full evaluation: a conversation with real execution in the oracle."""
    mensajes = [{"role": "system", "content": prompt}, {"role": "user", "content": texto}]
    llamadas, pasos, t0 = [], 0, time.time()
    respuesta_texto = ""
    ejecutor.sesion_iniciar()
    if args.navegador and _necesita_navegador(caso):
        ejecutor._entorno("browser-up", timeout=120)
    tarea = comp_ok = None
    comp_detalle = ""
    try:
        for _ in range(MAX_TURNOS):
            msg = preguntar(args.url, clave, args.modelo, mensajes, tools,
                            extra=getattr(args, "extra_peticion", None))
            tcs = msg.get("tool_calls") or []
            respuesta_texto = (msg.get("content") or "").strip()
            mensajes.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": tcs} if tcs else
                            {"role": "assistant", "content": msg.get("content") or ""})
            if not tcs:
                break
            pasos += 1
            for tc in tcs:
                f = tc.get("function", {})
                nombre = f.get("name", "")
                try:
                    a = json.loads(f.get("arguments") or "{}")
                except Exception:
                    a = {"_crudo": f.get("arguments")}
                llamadas.append({"nombre": nombre, "args": a})
                mensajes.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": ejecutor.ejecutar(nombre, a)})

        # The case's own tool is exercised in the FINAL STATE, before resetting.
        if args.comprobacion:
            comp_ok, comp_detalle = comprobar(caso, capa)

        # task check on the FINAL STATE of the oracle, as in v1
        cf = caso.get("comprobar_final")
        if cf:
            salida = ejecutor._en_oraculo(
                "import sys; sys.path.insert(0, %r)\n"
                "import tools\nprint(tools.execute_tool('run_command', "
                "{'command': %r}))" % (ejecutor.AGENTE_EN_ORACULO, cf["comando"]))
            esperado = cf.get("espera_contiene", "")
            if esperado:
                tarea = esperado in salida
            else:
                tarea = bool(salida.strip()) and "(no output)" not in salida
    finally:
        ejecutor.sesion_terminar()

    p = puntuar(caso, llamadas, respuesta_texto, capa)

    # The closing answer, checked against what the case says is true. Without this
    # the bench only knew which tool was called, and that is how it came to pass
    # "0 packages installed" (false) while failing "432" (true).
    resp_ok = revisar(caso, respuesta_texto)
    p["respuesta_ok"] = resp_ok
    p["respuesta_detalle"] = detalle(caso, respuesta_texto) if resp_ok is False else ""

    p.update({"caso": caso["id"], "grupo": caso["grupo"], "idioma": idioma, "tipo": caso["tipo"],
              "pasos": pasos, "segundos": round(time.time() - t0, 1),
              "tarea_ok": tarea, "comprobacion_ok": comp_ok,
              "texto_final": respuesta_texto[:300],
              "herramienta_usada": ",".join(l["nombre"] for l in llamadas) or "(texto)"})
    # A failed comprobacion means the environment could not run the tool: there is
    # no measurement. It is recorded as an instrument failure and excluded.
    if comp_ok is False:
        p["error"] = "INSTRUMENT: comprobacion failed (%s)" % comp_detalle
    p["_ok"] = (p["_ok"] and (tarea is not False) and (comp_ok is not False)
                and (resp_ok is not False))
    if resp_ok is False:
        print("       the closing answer does not carry the expected data: %s"
              % p["respuesta_detalle"][:120])
    return p, mensajes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("AIOS_LLM_URL", "https://webuillama.ccmai.org"))
    ap.add_argument("--modelo", default=os.environ.get("AIOS_LLM_MODEL", "qwen3"))
    ap.add_argument("--idioma", default=None)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--solo", default=None, help="comma-separated case prefixes")
    ap.add_argument("--etiqueta", default="multipaso-v2")
    ap.add_argument("--json-salida", default=None)
    ap.add_argument("--sin-trayectorias", action="store_true")
    ap.add_argument("--sin-comprobacion", dest="comprobacion", action="store_false",
                    help="skip the tool-execution check (faster, weaker)")
    ap.add_argument("--sin-navegador", dest="navegador", action="store_false",
                    help="do not start chromium for the browser_* cases")
    ap.add_argument("--prompt", default="prompt_produccion.txt",
                    help="which system prompt file to use (default: production)")
    ap.add_argument("--sin-thinking", action="store_true")
    args = ap.parse_args()

    args.extra_peticion = ({"chat_template_kwargs": {"enable_thinking": False}}
                           if args.sin_thinking else None)

    banco = _cargar("casos.json")
    prompt = open(os.path.join(BASE, args.prompt), encoding="utf-8").read()
    tools = _cargar("tools.json")
    capa = ejecutor._capa()
    clave = leer_clave_api()

    idiomas = [args.idioma] if args.idioma else banco["idiomas"]
    casos = banco["casos"]
    if args.solo:
        pref = [p.strip() for p in args.solo.split(",") if p.strip()]
        casos = [c for c in casos if any(c["id"].startswith(p) for p in pref)]
    if args.limite:
        casos = casos[:args.limite]

    salida = args.json_salida or os.path.join(BASE, "resultado_%s.json" % args.etiqueta)
    parcial = os.path.join(BASE, "resultado_%s_parcial.json" % args.etiqueta)
    tray_path = os.path.join(BASE, "trayectorias_%s.jsonl" % args.etiqueta)
    tray = open(tray_path, "w", encoding="utf-8") if not args.sin_trayectorias else None

    print("=" * 96)
    print("MULTI-STEP BENCH OF aios-llm  —  v2 (shipped code)     label: %s" % args.etiqueta)
    print("=" * 96)
    print("bench         : casos.json v%s  (%d cases)" % (banco.get("version"), len(banco["casos"])))
    print("endpoint      : %s   (key: %s)" % (args.url, "yes" if clave else "no"))
    print("system prompt : %d chars (%s)" % (len(prompt), args.prompt))
    print("tools         : %d" % len(tools))
    print("evaluations   : %d cases x %d languages = %d  (up to %d steps each)"
          % (len(casos), len(idiomas), len(casos) * len(idiomas), MAX_TURNOS))
    print("tool check    : %s" % ("on" if args.comprobacion else "OFF"))
    print("=" * 96)

    filas = []
    for caso in casos:
        for idioma in idiomas:
            texto = caso["idiomas"].get(idioma)
            if not texto:
                continue
            try:
                p, mensajes = evaluar(caso, idioma, texto, args, prompt, tools, capa, clave)
            except Exception as e:
                p = {"caso": caso["id"], "grupo": caso["grupo"], "idioma": idioma,
                     "tipo": caso["tipo"], "_ok": False, "error": str(e), "pasos": 0}
                mensajes = []
                print("  ERROR %-26s %-3s %s" % (caso["id"], idioma, str(e)[:70]))
            filas.append(p)
            if tray and mensajes:
                tray.write(json.dumps({"caso": caso["id"], "idioma": idioma,
                                       "peticion": texto, "mensajes": mensajes},
                                      ensure_ascii=False) + "\n")
                tray.flush()
            json.dump({"etiqueta": args.etiqueta, "parcial": True, "filas": filas},
                      open(parcial, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            marca = "OK   " if p.get("_ok") else ("INSTR" if p.get("error") else "FAIL ")
            extra = ""
            if p.get("error"):
                extra += " " + str(p["error"])[:60]
            if not p.get("herramienta"):
                extra += " tool:" + p.get("herramienta_usada", "?")
            if not p.get("argumentos"):
                extra += " bad-args"
            if not p.get("prohibido"):
                extra += " FORBIDDEN:" + ",".join(p.get("_encontrados", []))
            if not p.get("seguridad"):
                extra += " DANGER:" + ";".join(p.get("_bloqueados", []))
            if p.get("comprobacion_ok") is not None:
                extra += " check:%s" % ("yes" if p["comprobacion_ok"] else "NO")
            if p.get("tarea_ok") is not None:
                extra += " task:%s" % ("yes" if p["tarea_ok"] else "no")
            print("  %s %-26s %-3s %5.1fs %dp %s%s" % (marca, caso["id"], idioma,
                                                       p.get("segundos", 0), p.get("pasos", 0),
                                                       p.get("herramienta_usada", ""), extra))

    validas = [f for f in filas if "error" not in f]
    instrumento = [f for f in filas if "error" in f]
    ok = sum(1 for f in validas if f.get("_ok"))
    print("\n" + "=" * 96)
    # Both numbers are reported: dividing by every row hides instrument failures,
    # and dividing only by valid rows hides how many there were.
    print("SCORE (measurable evaluations): %d/%d = %.1f%%"
          % (ok, len(validas), 100.0 * ok / max(1, len(validas))))
    print("INSTRUMENT FAILURES           : %d of %d evaluations (%s)"
          % (len(instrumento), len(filas),
             ", ".join("%s/%s" % (f["caso"], f["idioma"]) for f in instrumento) or "none"))
    if instrumento:
        print("  -> these are NOT model failures. Fix the bench/oracle and re-run those cases.")

    def tabla(clave_agrup, titulo):
        print("\n%s" % titulo)
        g = {}
        for f in validas:
            g.setdefault(f.get(clave_agrup, "?"), []).append(f)
        for k in sorted(g):
            v = g[k]
            print("   %-16s %2d/%2d  %3.0f%%" % (k, sum(1 for x in v if x.get("_ok")), len(v),
                                                 100.0 * sum(1 for x in v if x.get("_ok")) / len(v)))

    tabla("grupo", "BY GROUP")
    tabla("idioma", "BY LANGUAGE")

    pasos = [f["pasos"] for f in validas if f.get("pasos")]
    if pasos:
        print("\nSTEPS: mean %.1f per evaluation (max %d)  |  one step = one round trip with"
              " real execution" % (sum(pasos) / len(pasos), max(pasos)))
    seg = [f["segundos"] for f in validas if f.get("segundos")]
    if seg:
        print("TIME: mean %.1fs per evaluation" % (sum(seg) / len(seg)))

    trampas = [f for f in validas if f.get("tipo") == "trampa"]
    if trampas:
        to = sum(1 for f in trampas if f.get("_ok"))
        print("\n" + "!" * 96)
        print("SECURITY TRAPS: %d/%d   <- the number that really matters" % (to, len(trampas)))
        for f in trampas:
            if not f.get("_ok"):
                print("   FAIL  %-26s %-3s used=%s" % (f["caso"], f["idioma"],
                                                        f.get("herramienta_usada", "?")))
        print("!" * 96)

    comp = [f for f in validas if f.get("comprobacion_ok") is not None]
    if comp:
        print("\nTOOLS EXERCISED AND CHECKED: %d/%d"
              % (sum(1 for f in comp if f["comprobacion_ok"]), len(comp)))

    tareas = [f for f in validas if f.get("tarea_ok") is not None]
    if tareas:
        print("TASKS CHECKED IN THE ORACLE : %d/%d"
              % (sum(1 for f in tareas if f["tarea_ok"]), len(tareas)))

    json.dump({"etiqueta": args.etiqueta, "bench": banco.get("version"), "filas": filas},
              open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\ndetails: %s" % salida)
    if tray:
        print("trajectories (training material): %s" % tray_path)


if __name__ == "__main__":
    main()
