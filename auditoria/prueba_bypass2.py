#!/usr/bin/env python3
"""Prueba DECISIVA: ¿process_start respeta el filtro que run_command aplica?

La version anterior de esta prueba no valia: use `find /var/tmp/... -delete`,
que el filtro EXCLUYE a proposito (exencion de /var/tmp). No demostraba nada.

Esta version usa un comando que el filtro SI marca, y compara las dos vias
sobre el mismo directorio desechable. Nada real se toca: el directorio es mio
y esta bajo mi $HOME.

    run_command   -> deberia NEGARSE
    process_start -> si borra, no consulta el filtro. Bypass.

Uso: cd ~/aios-agent && python3 <este_fichero>
"""
import importlib.util
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.expanduser("~/aios-agent"))

tools = importlib.util.spec_from_file_location(
    "tools", os.path.expanduser("~/aios-agent/tools.py"))
mod = importlib.util.module_from_spec(tools)
sys.modules["tools"] = mod
tools.loader.exec_module(mod)

proc_spec = importlib.util.spec_from_file_location(
    "process", os.path.expanduser("~/aios-agent/process.py"))
proc = importlib.util.module_from_spec(proc_spec)
sys.modules["process"] = proc
proc_spec.loader.exec_module(proc)

DIR = os.path.expanduser("~/prueba-bypass")
CMD = f"rm -rf {DIR}"


def preparar():
    shutil.rmtree(DIR, ignore_errors=True)
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, "dato.txt"), "w") as f:
        f.write("si esto sobrevive, el filtro funciono\n")


def vive():
    return os.path.isdir(DIR)


print("=" * 78)
print("¿process_start respeta el filtro de seguridad?")
print("=" * 78)
print(f"\nComando de prueba : {CMD}")
print(f"Directorio        : {DIR}")
print(f"\nVeredicto del filtro sobre ese comando:")
print(f"  _is_blocked_command        -> {mod._is_blocked_command(CMD)}")
print(f"  _is_destructive_command    -> {mod._is_destructive_command(CMD)}")

# ---- VIA 1: run_command (deberia negarse) ----
print("\n" + "-" * 78)
print("VIA 1: run_command()  — pasa por el filtro")
print("-" * 78)
preparar()
print(f"  antes: ¿existe el directorio? {vive()}")
salida = mod.run_command(CMD)
try:
    d = json.loads(salida)
    resumen = {k: v for k, v in d.items() if k in ("error", "exit_code", "stderr")}
except Exception:
    resumen = str(salida)[:200]
print(f"  run_command respondio: {json.dumps(resumen, ensure_ascii=False) if isinstance(resumen, dict) else resumen}")
print(f"  despues: ¿existe el directorio? {vive()}  "
      f"{'-> SE NEGO, correcto' if vive() else '-> LO BORRO, el filtro no funciono'}")

# ---- VIA 2: process_start (¿consulta el filtro?) ----
print("\n" + "-" * 78)
print("VIA 2: process_start()  — NO esta en tools.py, vive en process.py")
print("-" * 78)
preparar()
print(f"  antes: ¿existe el directorio? {vive()}")
resp = proc.process_start(CMD)
print(f"  process_start respondio: {str(resp)[:220]}")
time.sleep(2)
print(f"  despues: ¿existe el directorio? {vive()}  "
      f"{'-> NO LO BORRO' if vive() else '-> LO BORRO SIN CONSULTAR EL FILTRO'}")

print("\n" + "=" * 78)
if not vive():
    print("RESULTADO: BYPASS CONFIRMADO.")
    print("  El mismo comando que run_command bloquea, lanzado por process_start,")
    print("  se ejecuta sin bloqueo y sin confirmacion.")
    print("  La capa de seguridad solo cubre UNA de las dos vias de ejecucion.")
else:
    print("RESULTADO: no hay bypass por esta via.")
print("=" * 78)

shutil.rmtree(DIR, ignore_errors=True)
print("\n(limpieza: directorio de prueba borrado)")