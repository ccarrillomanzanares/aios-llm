#!/usr/bin/env python3
"""NON-REGRESSION bench of the aios-agent security layer.

The REAL functions from tools.py are imported and fed a table of cases with the
verdict they must give. This file is the CONTRACT of the layer: if something
future breaks a case, it shows up here.

Usage (on the VPS):
    cd ~/aios-agent && PYTHONPATH=$HOME/aios-agent python3 <this_file>

History:
  26 Sep 2026  first version  -> 27/41  (14 failures, see AUDITORIA)
  26 Sep 2026  after the fixes -> this file, 54 cases
"""
import importlib.util
import os
import sys

def _localizar_tools():
    """Finds tools.py: next to the script, in its parent directory, or in ~/aios-agent."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    for c in (aqui, os.path.dirname(aqui), os.path.expanduser("~/aios-agent")):
        p = os.path.join(c, "tools.py")
        if os.path.isfile(p):
            return p
    raise SystemExit("Cannot find tools.py (tried: next to the script, its parent, ~/aios-agent)")


RUTA = _localizar_tools()
# tools.py imports its siblings (process, software_inventory...): its directory
# has to be in sys.path so that the bench is self-contained, without PYTHONPATH.
sys.path.insert(0, os.path.dirname(RUTA))
spec = importlib.util.spec_from_file_location("aios_tools", RUTA)
m = importlib.util.module_from_spec(spec)
sys.modules["aios_tools"] = m
spec.loader.exec_module(m)

veredicto = m.verificar_comando
print("Bench of the aios-agent security layer")
print("Functions loaded from %s\n" % RUTA)

B, C, P = "BLOCKS", "CONFIRM", "PASSES"

CASOS = [
    # ── 1. IRREVERSIBLE: it never runs, not even with permission ──────────────
    ("rm -rf /",                          B, "the canonical case"),
    ("rm -rf /*",                         B, "it used to ESCAPE to the confirmation level"),
    ("rm -rf --no-preserve-root /",       B, ""),
    ("rm -rf /var/lib/docker",            B, ""),
    ("dd if=/dev/zero of=/dev/sda",       B, "writing the disk"),
    ("mkfs.ext4 /dev/sda1",               B, "formatting"),
    ("fdisk /dev/sda",                    B, "partitioning"),
    ("shred -u /etc/passwd",              B, "irreversible by design"),
    ("wipefs -a /dev/sda",                B, ""),
    ("chmod 000 /etc/shadow",             B, ""),
    ("dockerd --host tcp://0.0.0.0:2375", B, "docker without TLS = root for everyone"),

    # ── 2. REQUIRES PERMISSION ────────────────────────────────────────────────
    ("rm -rf /home/usuario/cosa",         C, "it used to be BLOCKED forever"),
    ("rm -rf /var/log/viejo",             C, "the usability defect it had: it was not possible even with permission"),
    ("rm -rf build",                      C, "relative: it still asks for permission, conservative"),
    ("rm -r /var/lib/sven",               C, "HOLE B1: only 'rm -rf' was caught"),
    ("rm --recursive --force /home/x",    C, "HOLE B8: long options"),
    ("sudo rm /etc/passwd",               C, ""),
    ("sudo tee /etc/passwd",              C, "HOLE B2: tee was not in any list"),
    ("echo x | sudo tee /etc/passwd",     C, "HOLE B2 through a pipe"),
    ("cp /dev/null /etc/passwd",          C, "HOLE B4"),
    ("ln -sf /dev/null /etc/passwd",      C, "HOLE B5"),
    ("chown -R nobody /",                 C, "HOLE B6"),
    ("sven install docker",               C, "the bug that gave rise to the layer"),
    ("sven -y install docker",            C, "HOLE B3: flag between the verb and the package"),
    ("sven --yes install docker",         C, "HOLE B3"),
    ("apt-get install nginx",             C, "it does not exist in AIOS, but it is caught"),
    ("apt-get -y install nginx",          C, ""),
    ("pip install requests",              C, ""),
    ("systemctl mask firewalld",          C, ""),
    ("systemctl disable sshd",            C, ""),
    ("systemctl stop systemd-networkd",   C, "HOLE B7: cutting the network remotely"),
    ("systemctl restart sshd",            C, "HOLE B7: restarting what gives you access"),
    ("find /var/log -delete",             C, ""),
    ("truncate -s 0 /etc/passwd",         C, ""),
    ("echo x > /etc/passwd",              C, "overwriting with >"),
    ("mv /etc/passwd /tmp/",              C, "moving instead of deleting"),
    ("dd if=/dev/zero of=/tmp/x",         C, ""),

    # ── 3. BYPASSES THAT WERE OPEN (logic errors) ─────────────────────────────
    ("find /etc -delete && touch /tmp/x",          C, "C1: mentioning /tmp disabled the check"),
    ("truncate -s 0 /etc/passwd; touch /tmp/x",    C, "C1"),
    ("echo y > /etc/passwd >> /tmp/log",           C, "C2: a >> disabled the > check"),
    ("echo y >> /tmp/log > /etc/passwd",           C, "C2 in the other order"),
    ("rm -rf /var/log/viejo; touch /tmp/x",        C, "C1 applied to rm"),

    # ── 4. SHOULD DO NOTHING (if this is blocked, the assistant is useless) ───
    ("ls -la",                            P, ""),
    ("cat /etc/hostname",                 P, "reading is not writing"),
    ("df -h",                             P, ""),
    ("systemctl status sshd",             P, "read-only query"),
    ("systemctl restart nginx",           P, "normal service: it does not cut access"),
    ("echo hola > /tmp/x",                P, "/tmp is exempt on purpose"),
    ("echo a >> /tmp/log",                P, ""),
    ("rm -rf /tmp/basura",                P, "the /tmp exemption, which used to be unreachable"),
    ("sven list",                         P, "querying changes nothing"),
    ("cp /home/a /tmp/b",                 P, "destination outside the system"),
    ("tee /home/usuario/notas.txt",       P, "destination outside the system"),
    ("chmod -R 755 /home/usuario/proyecto", P, "recursive but over the home, not the system"),
]

fallos = []
anchos = max(len(c) for c, _, _ in CASOS)
print("%-8s %-*s %-9s %s" % ("MARK", anchos, "COMMAND", "ACTUAL", "NOTE"))
print("-" * 110)
for cmd, esperado, nota in CASOS:
    real, motivo = veredicto(cmd)
    real = {"bloquea": B, "confirma": C, "adelante": P}[real]
    ok = real == esperado
    if not ok:
        fallos.append((cmd, esperado, real, nota))
    print("%-8s %-*s %-9s %s" % ("OK" if ok else "FAIL", anchos, cmd, real,
                                 ("(expected %s) " % esperado if not ok else "") + nota))

print("\n" + "=" * 110)
print("RESULT: %d/%d correct, %d failures" % (len(CASOS) - len(fallos), len(CASOS), len(fallos)))
print("=" * 110)
if fallos:
    print("\nFAILURES:")
    for cmd, esp, real, nota in fallos:
        print("  [%s instead of %s] %s" % (real, esp, cmd))
        if nota:
            print("      %s" % nota)
sys.exit(1 if fallos else 0)
print("\nThe layer meets its contract. Zero failures.")