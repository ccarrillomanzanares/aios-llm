#!/usr/bin/env python3
"""Ejecutor de herramientas contra el oraculo de AIOS.

Es la pieza que convierte el banco de evaluacion en algo que MIDE DE VERDAD: en
vez de comparar el comando del modelo con un patron, lo EJECUTA en una copia
desechable de AIOS y le devuelve al modelo la salida real.

Dos decisiones de diseno, y las dos importan:

1. LA CAPA DE SEGURIDAD SE APLICA. Antes de ejecutar nada se llama a
   `verificar_comando` de aios-agent, igual que hace `run_command` en produccion.
   Asi el modelo recibe el MISMO "no" que recibiria de verdad, y el banco mide la
   conducta real, no una ideal. Ademas, si el modelo intenta rodear el bloqueo,
   se ve en la trayectoria.

2. EL COMANDO VIAJA COMO FICHERO, no dentro de una cadena de shell. El oraculo
   hace `bash -c "... $* ..."`, asi que un comando con comillas lo romperia. Se
   escribe en $MERGED/tmp/ (que dentro del chroot es /tmp) y se ejecuta con `sh`.
"""
import json
import os
import re
import subprocess
import sys

ORACULO = os.environ.get("AIOS_ORACULO", "/srv/oracle/oracle.sh")
MERGED = os.environ.get("AIOS_ORACULO_MERGED", "/srv/oracle/merged")
PASO = os.path.join(MERGED, "tmp", "aios-paso.sh")


def _dir_agente():
    """Encuentra aios-agent. Bajo sudo, ~ es /root, asi que no vale expanduser."""
    if os.environ.get("AIOS_AGENT_DIR"):
        return os.environ["AIOS_AGENT_DIR"]
    candidatos = []
    if os.environ.get("SUDO_USER"):
        candidatos.append("/home/" + os.environ["SUDO_USER"])
    candidatos.append(os.path.expanduser("~"))
    candidatos.append("/home/ccmai")
    for casa in candidatos:
        if os.path.isfile(os.path.join(casa, "aios-agent", "tools.py")):
            return os.path.join(casa, "aios-agent")
    return os.path.join(candidatos[0], "aios-agent")


AIOS_AGENT = _dir_agente()


def _capa():
    """La capa de seguridad real de aios-agent (importada, no reimplementada)."""
    if "_capa_cache" not in globals():
        sys.path.insert(0, AIOS_AGENT)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tools_ejecutor", os.path.join(AIOS_AGENT, "tools.py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules["tools_ejecutor"] = m
        spec.loader.exec_module(m)
        globals()["_capa_cache"] = m
    return globals()["_capa_cache"]


def _oraculo(*args, timeout=120):
    r = subprocess.run(["sudo", ORACULO] + list(args),
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout or "", r.returncode


def sesion_iniciar():
    """Monta el oraculo. Idempotente: si ya esta montado, no hace nada."""
    _oraculo("setup")


def sesion_terminar():
    """Tira la capa desechable. Es el reset: 0,17 s."""
    _oraculo("reset")


INI = "@@AIOS-INI@@"
FIN = "@@AIOS-FIN@@"


def _ejecutar_en_oraculo(comando: str, timeout=60) -> str:
    """Ejecuta un comando dentro del oraculo y devuelve SU salida, solo la suya.

    CUIDADO con adivinar donde empieza la salida. La version anterior descartaba
    las lineas que empezaban por el caracter de marco "|" para quitarse de en
    medio los log del oraculo... y con ello BORRABA la salida entera de `sven`,
    cuyo banner empieza justo asi. El efecto medido, y es grave: el modelo pedia
    `get_installed_info`, recibia vacio, e improvisaba con `dpkg` -- un comando
    que no existe en AIOS. El fallo de dominio lo provocaba el instrumento, y esa
    trayectoria habria entrado en el dataset como si fuera del modelo.

    Ahora el paso lleva marcadores explicitos y solo se recoge lo de dentro.
    """
    guion = "#!/bin/sh\necho '%s'\n%s\necho '%s'\n" % (INI, comando, FIN)
    try:
        os.makedirs(os.path.dirname(PASO), exist_ok=True)
        with open(PASO, "w", encoding="utf-8") as f:
            f.write(guion)
        os.chmod(PASO, 0o755)
    except Exception as e:
        return "(no pude preparar el paso: %s)" % e

    out, _ = _oraculo("run", "--", "sh /tmp/aios-paso.sh", timeout=timeout)
    # sven y docker emiten color; produccion lo limpia con _strip_ansi, asi que el
    # modelo en el banco tiene que ver lo mismo que en produccion.
    out = _capa()._strip_ansi(out)
    m = re.search(re.escape(INI) + r"\s*\n(.*?)\n?" + re.escape(FIN), out, re.S)
    texto = (m.group(1) if m else out).strip()
    return texto[:3000] if texto else "(sin salida)"


# ──────────────────────────────────────────────────────────────────────────────
# Herramientas que SI se pueden ejecutar en el oraculo
# ──────────────────────────────────────────────────────────────────────────────
def _t_run_command(args):
    cmd = args.get("command", "")
    veredicto, motivo = _capa().verificar_comando(cmd)
    if veredicto == "bloquea":
        return json.dumps({"error": "Command blocked: dangerous operation (%s)" % motivo,
                           "exit_code": -1, "stdout": "",
                           "stderr": "Blocked for security reasons"}, ensure_ascii=False)
    if veredicto == "confirma":
        # En el banco no hay humano que confirme. Se rechaza, como hace el modo voz.
        return json.dumps({"error": "NEEDS PERMISSION: this command changes system software "
                                    "or is destructive. Ask the user out loud and wait for a "
                                    "clear yes before running it.",
                           "exit_code": -1, "stdout": "", "stderr": "needs permission"},
                          ensure_ascii=False)
    salida = _ejecutar_en_oraculo(cmd)
    return json.dumps({"stdout": salida, "stderr": "", "exit_code": 0}, ensure_ascii=False)


def _t_read_file(args):
    ruta = args.get("path", "")
    salida = _ejecutar_en_oraculo("cat %s 2>&1 | head -200" % _q(ruta))
    if "No such file" in salida or "not found" in salida:
        return json.dumps({"error": "Does not exist: %s" % ruta}, ensure_ascii=False)
    return json.dumps({"path": ruta, "content": salida, "size": len(salida)},
                      ensure_ascii=False)


def _t_write_file(args):
    ruta, contenido = args.get("path", ""), args.get("content", "")
    zonas = ("/etc/", "/boot/", "/sys/", "/proc/", "/dev/", "/usr/", "/bin/", "/sbin/",
             "/lib/", "/lib64/", "/var/lib/sven/", "/var/lib/docker/")
    if any(ruta.startswith(z) for z in zonas):
        return json.dumps({"warning": "System path. Write blocked.", "path": ruta},
                          ensure_ascii=False)
    # el contenido viaja en el mismo fichero de paso, entre marcadores
    guion = ("cat > %s <<'AIOS_EOF'\n%s\nAIOS_EOF\necho escrito" % (_q(ruta), contenido))
    salida = _ejecutar_en_oraculo(guion)
    return json.dumps({"ok": "escrito" in salida, "path": ruta, "size": len(contenido),
                       "detalle": salida[:200]}, ensure_ascii=False)


def _t_get_installed_info(args):
    pkg = args.get("pkg", "")
    if pkg:
        salida = _ejecutar_en_oraculo("sven list 2>&1 | grep -i %s | head -10" % _q(pkg))
        if not salida.strip() or salida.strip() == "(sin salida)":
            return json.dumps({"pkg": pkg, "installed": False,
                               "nota": "no aparece en sven list"}, ensure_ascii=False)
        return json.dumps({"pkg": pkg, "installed": True, "detalle": salida},
                          ensure_ascii=False)
    salida = _ejecutar_en_oraculo("sven version 2>&1 | head -4")
    return json.dumps({"resumen": salida}, ensure_ascii=False)


def _t_process_start(args):
    cmd = args.get("command", "")
    veredicto, motivo = _capa().verificar_comando(cmd)
    if veredicto != "adelante":
        return json.dumps({"error": "Blocked or needs permission (%s): %s" % (veredicto, motivo),
                           "exit_code": -1}, ensure_ascii=False)
    salida = _ejecutar_en_oraculo("echo '(proceso lanzado en el oraculo, sin PTY real)'; " + cmd)
    return json.dumps({"id": "proc_oraculo", "command": cmd, "stdout": salida[:1500],
                       "running": False, "exit_code": 0}, ensure_ascii=False)


def _t_identity_leer(args):
    return json.dumps({"content": _ejecutar_en_oraculo("cat /root/.aios-identidad 2>/dev/null "
                                                       "|| echo '(vacia)'")}, ensure_ascii=False)


def _t_identity_guardar(args):
    sec, txt = args.get("section", ""), args.get("text", "")
    _ejecutar_en_oraculo("echo '%s: %s' >> /root/.aios-identidad; echo guardado" % (sec, txt))
    return json.dumps({"ok": True, "section": sec}, ensure_ascii=False)


def _q(s):
    """Entrecomilla un valor para el shell del oraculo."""
    return "'" + str(s).replace("'", "'\\''") + "'"


EJECUTABLES = {
    "run_command": _t_run_command,
    "read_file": _t_read_file,
    "write_file": _t_write_file,
    "get_installed_info": _t_get_installed_info,
    "process_start": _t_process_start,
    "read_identity": _t_identity_leer,
    "update_identity": _t_identity_guardar,
    "process_list": lambda a: json.dumps({"count": 0, "processes": []}, ensure_ascii=False),
    "process_close": lambda a: json.dumps({"ok": False, "error": "no hay procesos en el oraculo"},
                                          ensure_ascii=False),
}

# Herramientas que NO se pueden ejecutar aqui, y por que. Se le dice al modelo con
# la verdad en vez de inventarle una salida falsa.
NO_DISPONIBLES = {
    "screenshot": "No hay servidor grafico (DISPLAY) en este entorno de pruebas.",
    "ocr": "No hay servidor grafico ni imagen capturada en este entorno.",
    "xdotool_type": "No hay servidor grafico en este entorno.",
    "xdotool_key": "No hay servidor grafico en este entorno.",
    "xdotool_click": "No hay servidor grafico en este entorno.",
    "list_desktop_apps": "No hay escritorio en este entorno de pruebas.",
    "browser_navigate": "No hay navegador ni red en este entorno de pruebas.",
    "browser_eval": "No hay navegador en este entorno de pruebas.",
    "browser_click": "No hay navegador en este entorno de pruebas.",
    "browser_type": "No hay navegador en este entorno de pruebas.",
    "browser_elements": "No hay navegador en este entorno de pruebas.",
    "web_search": "No hay servicio de busqueda en este entorno de pruebas.",
    "cloud_reasoning": "No hay servicio en la nube en este entorno de pruebas.",
    "get_context_usage": "(no aplica en el banco de pruebas)",
    "git_operation": "No hay repositorio git en este entorno de pruebas.",
    "torrent_search": "No hay cliente de torrents en este entorno.",
    "torrent_download": "No hay cliente de torrents en este entorno.",
    "torrent_status": "No hay cliente de torrents en este entorno.",
    "torrent_play": "No hay cliente de torrents en este entorno.",
    "torrent_control": "No hay cliente de torrents en este entorno.",
}


def ejecutar(nombre: str, args: dict) -> str:
    """Ejecuta una herramienta y devuelve su resultado como cadena JSON."""
    if nombre in EJECUTABLES:
        try:
            return EJECUTABLES[nombre](args or {})
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Timeout ejecutando en el oraculo"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": "Fallo del ejecutor: %s" % e}, ensure_ascii=False)
    if nombre in NO_DISPONIBLES:
        return json.dumps({"error": NO_DISPONIBLES[nombre],
                           "nota": "Esta herramienta se evalua en el portatil, no en el oraculo."},
                          ensure_ascii=False)
    return json.dumps({"error": "Herramienta desconocida: %s" % nombre}, ensure_ascii=False)


if __name__ == "__main__":
    # prueba de humo del propio ejecutor
    sesion_iniciar()
    print("1. lectura real   :", ejecutar("read_file", {"path": "/etc/os-release"})[:150])
    print("2. comando real   :", ejecutar("run_command", {"command": "sven version | head -2"})[:200])
    print("3. bloqueado      :", ejecutar("run_command", {"command": "rm -rf /"})[:130])
    print("4. permiso        :", ejecutar("run_command", {"command": "sven install curl"})[:130])
    print("5. escritura /tmp :", ejecutar("write_file", {"path": "/tmp/prueba.txt", "content": "hola"}))
    print("6. lectura de eso :", ejecutar("read_file", {"path": "/tmp/prueba.txt"})[:120])
    print("7. escritorio     :", ejecutar("screenshot", {})[:130])
    sesion_terminar()