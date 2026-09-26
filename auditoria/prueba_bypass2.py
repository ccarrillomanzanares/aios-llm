#!/usr/bin/env python3
"""DECISIVE test: does process_start respect the filter that run_command applies?

The previous version of this test was worthless: it used `find /var/tmp/... -delete`,
which the filter EXCLUDES on purpose (/var/tmp exemption). It proved nothing.

This version uses a command that the filter DOES flag, and compares the two paths
over the same throwaway directory. Nothing real is touched: the directory is mine
and it is under my $HOME.

    run_command   -> should REFUSE
    process_start -> if it deletes, it does not consult the filter. Bypass.

Usage: cd ~/aios-agent && python3 <this_file>
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
        f.write("if this survives, the filter worked\n")


def vive():
    return os.path.isdir(DIR)


print("=" * 78)
print("Does process_start respect the security filter?")
print("=" * 78)
print(f"\nTest command : {CMD}")
print(f"Directory    : {DIR}")
print(f"\nFilter verdict on that command:")
print(f"  _is_blocked_command        -> {mod._is_blocked_command(CMD)}")
print(f"  _is_destructive_command    -> {mod._is_destructive_command(CMD)}")

# ---- PATH 1: run_command (should refuse) ----
print("\n" + "-" * 78)
print("PATH 1: run_command()  — goes through the filter")
print("-" * 78)
preparar()
print(f"  before: does the directory exist? {vive()}")
salida = mod.run_command(CMD)
try:
    d = json.loads(salida)
    resumen = {k: v for k, v in d.items() if k in ("error", "exit_code", "stderr")}
except Exception:
    resumen = str(salida)[:200]
print(f"  run_command replied: {json.dumps(resumen, ensure_ascii=False) if isinstance(resumen, dict) else resumen}")
print(f"  after: does the directory exist? {vive()}  "
      f"{'-> IT REFUSED, correct' if vive() else '-> IT DELETED IT, the filter did not work'}")

# ---- PATH 2: process_start (does it consult the filter?) ----
print("\n" + "-" * 78)
print("PATH 2: process_start()  — it is NOT in tools.py, it lives in process.py")
print("-" * 78)
preparar()
print(f"  before: does the directory exist? {vive()}")
resp = proc.process_start(CMD)
print(f"  process_start replied: {str(resp)[:220]}")
time.sleep(2)
print(f"  after: does the directory exist? {vive()}  "
      f"{'-> IT DID NOT DELETE IT' if vive() else '-> IT DELETED IT WITHOUT CONSULTING THE FILTER'}")

print("\n" + "=" * 78)
if not vive():
    print("RESULT: BYPASS CONFIRMED.")
    print("  The same command that run_command blocks, launched by process_start,")
    print("  runs with no block and no confirmation.")
    print("  The security layer only covers ONE of the two execution paths.")
else:
    print("RESULT: there is no bypass through this path.")
print("=" * 78)

shutil.rmtree(DIR, ignore_errors=True)
print("\n(cleanup: test directory deleted)")