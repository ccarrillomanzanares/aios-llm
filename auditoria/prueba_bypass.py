#!/usr/bin/env python3
"""HARMLESS tests for two holes found by reading the code.

1. process_start does NOT go through the security filter (process.py does not
   mention _is_blocked_command nor _is_destructive_command). It is shown with a
   command that the filter DOES flag as destructive, but over a temporary
   directory of mine: if it runs without any confirmation prompt appearing, the
   filter did not take part.

2. git_operation puts `args` inside a string that it runs with `shell=True`:
   command injection. It is shown with a harmless `; echo`.

None of this touches real files: /var/tmp/aios-prueba is mine and gets deleted.

Usage:  cd ~/aios-agent && PYTHONPATH=$HOME/aios-agent python3 <this_file>
"""
import importlib.util
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/aios-agent"))


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod          # so that the internal imports resolve
    spec.loader.exec_module(mod)
    return mod


tools = cargar("tools", os.path.expanduser("~/aios-agent/tools.py"))
process = cargar("process", os.path.expanduser("~/aios-agent/process.py"))

print("=" * 78)
print("HOLE 1 — does process_start respect the security filter?")
print("=" * 78)

PRUEBA = "/var/tmp/aios-prueba"
os.makedirs(PRUEBA, exist_ok=True)
with open(os.path.join(PRUEBA, "fichero.txt"), "w") as f:
    f.write("this must still be here if the filter works\n")

COMANDO = f"find {PRUEBA} -delete"
print(f"\nTest directory     : {PRUEBA}")
print(f"Content before     : {os.listdir(PRUEBA)}")
print(f"\nCommand to run     : {COMANDO}")
print(f"Does the filter flag it destructive?  _is_destructive_command -> "
      f"{tools._is_destructive_command(COMANDO)}")
print(f"Does the filter block it?             _is_blocked_command     -> "
      f"{tools._is_blocked_command(COMANDO)}")

print("\nNow the SAME command, but through process_start (without asking anything):")
try:
    # process_start returns session information; it is launched and closed
    salida = process.process_start(COMANDO)
    print(f"  process_start replied: {str(salida)[:200]}")
except Exception as e:
    print(f"  process_start raised an exception: {e}")

time.sleep(2)
try:
    existentes = os.listdir(PRUEBA)
except FileNotFoundError:
    existentes = []
print(f"\nContent AFTER      : {existentes if existentes else '(empty or deleted)'}")
if not existentes:
    print("  >>> CONFIRMED: the destructive command ran WITHOUT confirmation.")
    print("      run_command would have stopped it; process_start does not consult the filter.")
else:
    print("  >>> The filter intervened (or the command never ran).")

print()
print("=" * 78)
print("HOLE 2 — does git_operation accept command injection?")
print("=" * 78)
print("\nThe line of code is:")
print('  command = f"git -C {repo} {op} {args}"')
print("  subprocess.run(command, shell=True, ...)")
print("  args is concatenated WITHOUT ESCAPING inside a shell string.")
print("\nTest with a harmless `; echo` (it deletes and changes nothing):")
try:
    r = tools.git_operation("status", "; echo INYECTADO_POR_EL_MODELO")
    datos = json.loads(r) if isinstance(r, str) else r
    print(f"  output: {json.dumps(datos, ensure_ascii=False)[:300]}")
    if "INYECTADO_POR_EL_MODELO" in json.dumps(datos):
        print("  >>> CONFIRMED: the injected command ran.")
    else:
        print("  >>> marker not seen (check manually)")
except Exception as e:
    print(f"  exception: {e}")

print("\nNote: the repo of git_operation is pinned to /home/ccmai/sre-agent,")
print(f"      which is the OLD name of the project. Does it exist? -> {os.path.isdir('/home/ccmai/sre-agent')}")

# cleanup
try:
    os.makedirs(PRUEBA, exist_ok=True)
    for f in os.listdir(PRUEBA):
        os.remove(os.path.join(PRUEBA, f))
    os.rmdir(PRUEBA)
except Exception:
    pass