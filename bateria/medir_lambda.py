#!/usr/bin/env python3
"""Measure the professor on Lambda against the VPS, with the REAL production prompt.

The interesting number is not "how fast is the GPU" in the abstract: it is how long
one call of the bench takes, because that, times the number of calls, is the bill.

Prompt: prompt_produccion.txt + the 29 real tool schemas -- the same bytes the bench
sends, so the comparison is against the VPS figure that was measured the same way
(52.9 s first call, ~18 s warm).
"""
import json, os, sys, time, urllib.request

BASE = "/home/ccmai/aios-llm/bateria"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://10.200.0.1:8085"
MODELO = sys.argv[2] if len(sys.argv) > 2 else "/home/ubuntu/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"

prompt = open(os.path.join(BASE, "prompt_produccion.txt"), encoding="utf-8").read()
tools = json.load(open(os.path.join(BASE, "tools.json"), encoding="utf-8"))
if isinstance(tools, dict):
    tools = tools.get("tools", tools.get("herramientas", list(tools.values())[0]))

texto = ("Instala el paquete curl y dime con que version ha quedado. "
         "Usa las herramientas disponibles cuando hagan falta.")

cuerpo = {
    "model": MODELO,
    "messages": [{"role": "system", "content": prompt},
                 {"role": "user", "content": texto}],
    "tools": tools, "tool_choice": "auto",
    "temperature": 0.0, "max_tokens": 400,
}

def llama(etiqueta, cuerpo):
    datos = json.dumps(cuerpo).encode("utf-8")
    pet = urllib.request.Request(URL.rstrip("/") + "/v1/chat/completions", data=datos)
    pet.add_header("Content-Type", "application/json")
    t = time.time()
    with urllib.request.urlopen(pet, timeout=600) as r:
        d = json.loads(r.read().decode("utf-8"))
    dt = time.time() - t
    m = d["choices"][0]["message"]
    u = d.get("usage") or {}
    print("  %-22s %7.2f s   prompt=%s tok  salida=%s tok" %
          (etiqueta, dt, u.get("prompt_tokens", "?"), u.get("completion_tokens", "?")))
    tc = m.get("tool_calls") or []
    if tc:
        print("       -> llamo a la herramienta: %s" % tc[0]["function"]["name"])
    else:
        print("       -> respondio en texto: %s" % (m.get("content") or "")[:70].replace("\n", " "))
    return dt

print("endpoint: %s" % URL)
print("prompt  : %d chars   tools: %d" % (len(prompt), len(tools)))
print()
print("--- llamadas REALES, tal cual las manda el banco ---")
t1 = llama("1a llamada (frio)", cuerpo)
t2 = llama("2a llamada (caliente)", cuerpo)
t3 = llama("3a llamada (caliente)", cuerpo)

# Y ahora el caso que de verdad domina el tiempo: los mensajes crecen en cada paso
# de la trayectoria, asi que el numero util es una llamada con el historial lleno.
largo = json.dumps(cuerpo)
print()
print("--- el caso que domina el coste: historial crecido ---")
cuerpo2 = dict(cuerpo)
cuerpo2["messages"] = cuerpo["messages"] + [
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "run_command", "arguments": '{"command":"sven install curl"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "run_command",
     "content": "installing...\n" + ("linea de salida real\n" * 400)},
]
t4 = llama("con historial", cuerpo2)

print()
print("RESUMEN  frio=%.1fs  caliente=%.1fs  con historial=%.1fs" % (t1, t2, t3 if t3 else 0))
print("En el VPS (CPU, 14 hilos) los mismos numeros fueron: frio 52.9s  caliente 4.0s"
      "  y el build genera a 10-16 tok/s")
print("Media de las 3 primeras: %.2f s" % ((t1 + t2 + t3) / 3))
print("Con historial (lo normal en una trayectoria): %.2f s" % t4)
