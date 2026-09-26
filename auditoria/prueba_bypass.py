#!/usr/bin/env python3
"""Pruebas INOFENSIVAS de dos agujeros detectados leyendo el codigo.

1. process_start NO pasa por el filtro de seguridad (process.py no menciona
   _is_blocked_command ni _is_destructive_command). Se demuestra con un
   comando que el filtro SI marca como destructivo, pero sobre un directorio
   temporal mio: si se ejecuta sin que aparezca ninguna peticion de
   confirmacion, el filtro no intervino.

2. git_operation mete `args` dentro de una cadena que ejecuta `shell=True`:
   inyeccion de comandos. Se demuestra con un `; echo` inofensivo.

Nada de esto toca ficheros reales: /var/tmp/aios-prueba es mio y se borra.

Uso:  cd ~/aios-agent && PYTHONPATH=$HOME/aios-agent python3 <este_fichero>
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
    sys.modules[nombre] = mod          # para que los imports internos se resuelvan
    spec.loader.exec_module(mod)
    return mod


tools = cargar("tools", os.path.expanduser("~/aios-agent/tools.py"))
process = cargar("process", os.path.expanduser("~/aios-agent/process.py"))

print("=" * 78)
print("AGUJERO 1 — ¿process_start respeta el filtro de seguridad?")
print("=" * 78)

PRUEBA = "/var/tmp/aios-prueba"
os.makedirs(PRUEBA, exist_ok=True)
with open(os.path.join(PRUEBA, "fichero.txt"), "w") as f:
    f.write("esto debe seguir aqui si el filtro funciona\n")

COMANDO = f"find {PRUEBA} -delete"
print(f"\nDirectorio de prueba: {PRUEBA}")
print(f"Contenido antes      : {os.listdir(PRUEBA)}")
print(f"\nComando a ejecutar   : {COMANDO}")
print(f"¿El filtro lo marca destructivo?  _is_destructive_command -> "
      f"{tools._is_destructive_command(COMANDO)}")
print(f"¿El filtro lo bloquea?            _is_blocked_command     -> "
      f"{tools._is_blocked_command(COMANDO)}")

print("\nAhora el MISMO comando, pero por process_start (sin pedir nada):")
try:
    # process_start devuelve informacion de la sesion; se lanza y se cierra
    salida = process.process_start(COMANDO)
    print(f"  process_start respondio: {str(salida)[:200]}")
except Exception as e:
    print(f"  process_start lanzo una excepcion: {e}")

time.sleep(2)
try:
    existentes = os.listdir(PRUEBA)
except FileNotFoundError:
    existentes = []
print(f"\nContenido DESPUES   : {existentes if existentes else '(vacio o borrado)'}")
if not existentes:
    print("  >>> CONFIRMADO: el comando destructivo se ejecuto SIN confirmacion.")
    print("      run_command lo habria frenado; process_start no consulta el filtro.")
else:
    print("  >>> El filtro intervino (o el comando no llego a correr).")

print()
print("=" * 78)
print("AGUJERO 2 — ¿git_operation acepta inyeccion de comandos?")
print("=" * 78)
print("\nLa linea del codigo es:")
print('  command = f"git -C {repo} {op} {args}"')
print("  subprocess.run(command, shell=True, ...)")
print("  args se concatena SIN ESCAPAR dentro de una cadena de shell.")
print("\nPrueba con un `; echo` inofensivo (no borra ni cambia nada):")
try:
    r = tools.git_operation("status", "; echo INYECTADO_POR_EL_MODELO")
    datos = json.loads(r) if isinstance(r, str) else r
    print(f"  salida: {json.dumps(datos, ensure_ascii=False)[:300]}")
    if "INYECTADO_POR_EL_MODELO" in json.dumps(datos):
        print("  >>> CONFIRMADO: el comando inyectado se ejecuto.")
    else:
        print("  >>> no se vio el marcador (revisar manualmente)")
except Exception as e:
    print(f"  excepcion: {e}")

print("\nNota: el repo de git_operation esta fijado a /home/ccmai/sre-agent,")
print(f"      que es el nombre VIEJO del proyecto. ¿existe? -> {os.path.isdir('/home/ccmai/sre-agent')}")

# limpieza
try:
    os.makedirs(PRUEBA, exist_ok=True)
    for f in os.listdir(PRUEBA):
        os.remove(os.path.join(PRUEBA, f))
    os.rmdir(PRUEBA)
except Exception:
    pass