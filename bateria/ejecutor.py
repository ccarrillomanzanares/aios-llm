#!/usr/bin/env python3
"""Tool executor against the AIOS oracle.

This is the piece that turns the bench into something that REALLY MEASURES: instead
of comparing the model's command against a pattern, it EXECUTES it in a throwaway
copy of AIOS and returns the real output to the model.

Two design decisions, and both of them matter:

1. THE SECURITY LAYER IS APPLIED. Before running anything, `verificar_comando` from
   aios-agent is called, exactly as `run_command` does in production.
   That way the model receives the SAME "no" it would really get, and the bench
   measures real behaviour, not an ideal one. On top of that, if the model tries to
   go around the block, it shows in the trajectory.

2. THE COMMAND TRAVELS AS A FILE, not inside a shell string. The oracle
   does `bash -c "... $* ..."`, so a command with quotes would break it. It is
   written to $MERGED/tmp/ (which inside the chroot is /tmp) and run with `sh`.
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
    """Finds aios-agent. Under sudo, ~ is /root, so expanduser is no good."""
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
    """The real security layer of aios-agent (imported, not reimplemented)."""
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
    """Brings the oracle up. Idempotent: if it is already up, it does nothing."""
    _oraculo("setup")


def sesion_terminar():
    """Tears down the throwaway layer. This is the reset: 0.17 s."""
    _oraculo("reset")


INI = "@@AIOS-INI@@"
FIN = "@@AIOS-FIN@@"


def _ejecutar_en_oraculo(comando: str, timeout=60) -> str:
    """Runs a command inside the oracle and returns ITS output, only its own.

    BEWARE of guessing where the output starts. The previous version discarded the
    lines beginning with the frame character "|" to get the oracle logs out of
    the way... and with that it WIPED OUT the whole output of `sven`, whose banner
    starts exactly like that. The effect measured, and it is serious: the model asked
    for `get_installed_info`, got back nothing, and improvised with `dpkg` -- a command
    that does not exist in AIOS. The domain failure was caused by the instrument, and
    that trajectory would have entered the dataset as if it were the model's.

    Now the step carries explicit markers and only what is inside them is collected.
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
    # sven and docker emit color; production cleans it with _strip_ansi, so the
    # model on the bench has to see the same as in production.
    out = _capa()._strip_ansi(out)
    m = re.search(re.escape(INI) + r"\s*\n(.*?)\n?" + re.escape(FIN), out, re.S)
    texto = (m.group(1) if m else out).strip()
    return texto[:3000] if texto else "(sin salida)"


# ──────────────────────────────────────────────────────────────────────────────
# Tools that CAN be executed in the oracle
# ──────────────────────────────────────────────────────────────────────────────
def _t_run_command(args):
    cmd = args.get("command", "")
    veredicto, motivo = _capa().verificar_comando(cmd)
    if veredicto == "bloquea":
        return json.dumps({"error": "Command blocked: dangerous operation (%s)" % motivo,
                           "exit_code": -1, "stdout": "",
                           "stderr": "Blocked for security reasons"}, ensure_ascii=False)
    if veredicto == "confirma":
        # On the bench there is no human to confirm. It is rejected, as voice mode does.
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
    # the content travels in the same step file, between markers
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
    """Quotes a value for the oracle's shell."""
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

# Tools that CANNOT be executed here, and why. The model is told the truth instead
# of having a fake output made up for it.
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
    """Runs a tool and returns its result as a JSON string."""
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
    # smoke test of the executor itself
    sesion_iniciar()
    print("1. real read      :", ejecutar("read_file", {"path": "/etc/os-release"})[:150])
    print("2. real command   :", ejecutar("run_command", {"command": "sven version | head -2"})[:200])
    print("3. blocked        :", ejecutar("run_command", {"command": "rm -rf /"})[:130])
    print("4. permission     :", ejecutar("run_command", {"command": "sven install curl"})[:130])
    print("5. write /tmp     :", ejecutar("write_file", {"path": "/tmp/prueba.txt", "content": "hola"}))
    print("6. read it back   :", ejecutar("read_file", {"path": "/tmp/prueba.txt"})[:120])
    print("7. desktop        :", ejecutar("screenshot", {})[:130])
    sesion_terminar()