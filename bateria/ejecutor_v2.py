#!/usr/bin/env python3
"""Tool executor against the AIOS oracle — v2, the one that runs the shipped code.

WHY THERE ARE TWO OF THEM

`ejecutor.py` (v1) is kept, untouched, because it produced the baseline the whole
project is measured against (35B: 173/174, traps 53/54). Replacing it would have
invalidated that number, and a baseline you cannot reproduce is not a baseline.

v1 translates each tool into a shell command and runs it. That measures an IDEAL
agent — one that behaves like the author imagined. v2 calls the agent's real
dispatcher, `tools.execute_tool(name, args)`, INSIDE the oracle, so the model
receives exactly what a user would receive. Same bench, same scoring, same
trajectories; the difference is that the thing being measured is the thing that
will ship.

WHAT CHANGED BY MEASURING (27 sep)

  * The whole tool surface is now exercisable in the oracle, all 29 of them.
    `screenshot`, `ocr` and `xdotool_*` work because the VPS has a virtual DRM
    card (`vkms`) and Xorg on top of it gives a real X server. `browser_*` work
    because chromium with CDP can be started inside the chroot. `torrent_search`
    works because the oracle kept the internet. The acceptance laptop is no
    longer needed for any of them — which was the last thing on the critical path
    that depended on a machine we do not control.

  * `run_command` goes through the dispatcher too, and that is a gain: the real
    `run_command` consults the security layer itself, so the model now gets the
    REAL refusal string — the same one a user would see — instead of one the
    bench wrote by hand. A bench that invents the refusal cannot notice when the
    refusal changes.

A BROKEN INSTRUMENT CONTAMINATES THE MATERIAL. An earlier version discarded the
output lines beginning with the oracle's frame character to silence its logs, and
with that it erased the whole output of `sven`, whose banner starts the same way.
The model asked `get_installed_info`, received nothing, and improvised with
`dpkg` — a command that does not exist in AIOS. That domain failure was the
instrument's, and the trajectory would have entered the dataset as the model's.
Output is now collected between explicit markers and nothing else is touched.

The per-case environment (network, X, staged agent, fixtures) belongs to
`oracle/entorno.sh`; this file assumes it is up.
"""
import json
import os
import re
import subprocess
import sys

ORACULO = os.environ.get("AIOS_ORACULO", "/srv/oracle/oracle.sh")
MERGED = os.environ.get("AIOS_ORACULO_MERGED", "/srv/oracle/merged")
NETNS = os.environ.get("AIOS_NETNS", "aios-orac")
AGENTE_EN_ORACULO = os.environ.get("AIOS_AGENT_EN_ORACULO", "/opt/aios-agent")
PASO_PY = os.path.join(MERGED, "tmp", "aios-paso.py")

INI = "@@AIOS-INI@@"
FIN = "@@AIOS-FIN@@"

# `entorno.sh` stages the agent inside the chroot and re-stages it after every
# reset, because the reset wipes /opt.
ENTORNO = os.path.join(os.path.dirname(ORACULO), "entorno.sh")


def _dir_agente():
    """Finds aios-agent on the host. Under sudo, ~ is /root, so expanduser is useless."""
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
    """The real security layer of aios-agent, imported on the HOST for scoring."""
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


def _netns(args, timeout=300):
    """Runs a command in the bench's own network namespace.

    The namespace is not optional. The VPS's own Xorg (lightdm) holds display
    :0's ABSTRACT socket, and aios-agent hard-codes DISPLAY=:0; without the
    namespace every desktop tool fails with "Authorization required" no matter
    what X is running. Isolating the network then costs the internet, so the
    namespace gets its own veth + NAT — that is entorno.sh's job.
    """
    r = subprocess.run(["sudo", "ip", "netns", "exec", NETNS] + list(args),
                       capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    return (r.stdout or ""), r.returncode


def _entorno(*args, timeout=600):
    r = subprocess.run(["sudo", ENTORNO] + list(args), capture_output=True,
                       text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def sesion_iniciar():
    """Brings the oracle up. Idempotent; it does NOT reset — the bench decides when."""
    _entorno("setup", timeout=600)


def sesion_terminar():
    """Resets the throwaway layer AND restores the bench environment.

    Through `entorno.sh`, not `oracle.sh`: a bare reset leaves the bench with no
    staged agent, no X socket and no fixtures, and the next case then fails for a
    reason that has nothing to do with the model. That is the silent-data-poisoning
    failure this project keeps having to defend against.
    """
    _entorno("reset", timeout=900)


def _en_oraculo(guion_python: str, timeout=180) -> str:
    """Runs python inside the AIOS chroot and returns only what it printed.

    Output is delimited by explicit markers; whatever else the oracle logs is
    discarded without guessing where the real output starts.
    """
    try:
        os.makedirs(os.path.dirname(PASO_PY), exist_ok=True)
        with open(PASO_PY, "w", encoding="utf-8") as f:
            f.write(guion_python)
    except Exception as e:
        return json.dumps({"error": "could not stage the step: %s" % e}, ensure_ascii=False)

    out, _ = _netns(["unshare", "--pid", "--uts", "--fork",
                     "--mount-proc=%s/proc" % MERGED,
                     "chroot", MERGED, "/bin/bash", "-c",
                     "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin;"
                     " export HOME=/root DISPLAY=:0; cd /root;"
                     " python3 /tmp/aios-paso.py"], timeout=timeout)
    out = _capa()._strip_ansi(out)
    m = re.search(re.escape(INI) + r"\s*\n(.*?)\n?" + re.escape(FIN), out, re.S)
    texto = (m.group(1) if m else out).strip()
    return texto[:4000] if texto else "(no output)"


def ejecutar(nombre: str, args: dict) -> str:
    """Runs a tool through the agent's REAL dispatcher and returns its real answer."""
    args = args or {}
    codigo = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "print(%r)\n"
        "try:\n"
        "    import tools\n"
        "    print(tools.execute_tool(%r, %s))\n"
        "except Exception as _e:\n"
        "    import traceback\n"
        "    print(json.dumps({'error': 'executor: ' + type(_e).__name__ + ': ' + str(_e)[:300]}))\n"
        "    traceback.print_exc()\n"
        "print(%r)\n"
        % (AGENTE_EN_ORACULO, INI, nombre, json.dumps(args, ensure_ascii=False), FIN))
    try:
        return _en_oraculo(codigo)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout executing in the oracle"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "executor failure: %s" % e}, ensure_ascii=False)


if __name__ == "__main__":
    sesion_iniciar()
    print("estado del entorno:")
    print(_entorno("check")[0])
    for nombre, a in [("read_file", {"path": "/etc/os-release"}),
                      ("run_command", {"command": "sven version | head -2"}),
                      ("run_command", {"command": "rm -rf /"}),
                      ("run_command", {"command": "sven install curl"}),
                      ("list_desktop_apps", {}),
                      ("get_context_usage", {}),
                      ("process_list", {}),
                      ("torrent_search", {"query": "Metropolis 1927 Fritz Lang", "limit": 2}),
                      ("screenshot", {}),
                      ("ocr", {"path": "/srv/banco/ocr-fixture.png"}),
                      ("xdotool_key", {"key": "Return"}),
                      ]:
        print("%-20s %s" % (nombre, ejecutar(nombre, a)[:200]))
    sesion_terminar()
