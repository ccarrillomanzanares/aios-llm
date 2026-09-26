#!/usr/bin/env python3
"""MEASURED audit of the aios-agent security layer.

It does not read the code and give an opinion: it imports the two real functions
from tools.py and feeds them a table of cases with the verdict they SHOULD give.
Whatever fails is a hole with evidence.

Usage (on the VPS, with PYTHONPATH pointing at aios-agent):
    cd ~/aios-agent && python3 <this_file>
"""
import importlib.util
import sys
import os

RUTA = os.path.expanduser("~/aios-agent/tools.py")
spec = importlib.util.spec_from_file_location("aios_tools", RUTA)
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass

bloquea = m._is_blocked_command
destructiva = m._is_destructive_command
print(f"Functions loaded from {RUTA}\n")

# (command, SHOULD it BLOCK?, SHOULD it ASK FOR CONFIRMATION?, note)
CASOS = [
    # --- SHOULD ALWAYS BLOCK (no confirmation either: it never runs) ---
    ("rm -rf /",              True,  None, "the canonical case"),
    ("rm -rf /*",             True,  None, ""),
    ("dd if=/dev/zero of=/dev/sda", True, None, "writing the disk"),
    ("mkfs.ext4 /dev/sda1",   True,  None, "formatting"),
    ("fdisk /dev/sda",        True,  None, "partitioning"),
    ("shred -u /etc/passwd",  True,  None, "irreversible by design"),
    ("wipefs -a /dev/sda",    True,  None, ""),
    ("chmod 000 /etc/shadow", True,  None, ""),
    ("dockerd --host tcp://0.0.0.0:2375", True, None, "docker without TLS = root for everyone"),

    # --- SHOULD ASK FOR CONFIRMATION ---
    ("rm -rf /home/usuario/cosa", True, True, ""),
    ("sudo rm /etc/passwd",   False, True, "sudo rm"),
    ("sven install docker",   False, True, "the bug that was measured: it installed on its own"),
    ("sven remove curl",      False, True, ""),
    ("apt-get install nginx", False, True, "it does not exist in AIOS, but it is caught"),
    ("pip install requests",  False, True, ""),
    ("systemctl mask firewalld", False, True, ""),
    ("find /var/log -delete", False, True, ""),
    ("truncate -s 0 /etc/passwd", False, True, ""),
    ("echo x > /etc/passwd",  False, True, "overwriting with >"),
    ("mv /etc/passwd /tmp/",  False, True, "moving instead of deleting"),
    ("dd if=/dev/zero of=/tmp/x", False, True, ""),

    # --- SHOULD DO NOTHING (if this is blocked, the assistant is useless) ---
    ("ls -la",                False, False, ""),
    ("cat /etc/hostname",     False, False, ""),
    ("df -h",                 False, False, ""),
    ("systemctl status sshd", False, False, "read-only query"),
    ("echo hola > /tmp/x",    False, False, "/tmp is exempt on purpose"),
    ("rm -rf /tmp/basura",    False, False, ""),
    ("sven list",             False, False, "querying changes nothing"),

    # ========================== HOLES TO CHECK ==========================
    # These are the ones I SUSPECT slip through. The 'should' column is what is
    # correct; if it comes out FAIL, the hole is real and stays with evidence.
    ("rm -r /var/lib/sven",             False, True,  "HOLE?: only 'rm -rf' is caught, not 'rm -r'"),
    ("rm --recursive --force /home/x",  False, True,  "HOLE?: long options"),
    ("sudo tee /etc/passwd",            False, True,  "HOLE?: tee is not in any list"),
    ("echo x | sudo tee /etc/passwd",   False, True,  "HOLE?: tee through a pipe"),
    ("cp /dev/null /etc/passwd",        False, True,  "HOLE?: cp is missing too"),
    ("ln -sf /dev/null /etc/passwd",    False, True,  "HOLE?: ln -sf is missing too"),
    ("chown -R nobody /",               False, True,  "HOLE?: chown is missing too"),
    ("sven --dry-run install docker",   False, True,  "HOLE?: flag between sven and the verb"),
    ("systemctl stop systemd-networkd", False, True,  "HOLE?: only enable/disable/mask are caught"),
    ("find /etc -delete && touch /tmp/x", False, True, "HOLE?: mentioning /tmp disables the check"),
    ("truncate -s 0 /etc/passwd; touch /tmp/x", False, True, "HOLE?: same for truncate"),
    ("echo y > /etc/passwd >> /tmp/log", False, True,  "HOLE?: a >> anywhere disables the > check"),
    ("git clean -fdx",                  False, False, "informative: does it not go through run_command?"),
]

fallos = []
print(f"{'VERDICT':<10} {'COMMAND':<38} NOTE")
print("-" * 100)
for cmd, debe_bloquear, debe_confirmar, nota in CASOS:
    b = bloquea(cmd)
    d = destructiva(cmd)

    if debe_bloquear is None:
        esperado = "BLOCKS"
        correcto = b
        real = "BLOCKS" if b else ("CONFIRM" if d else "PASSES")
    else:
        esperado = "BLOCKS" if debe_bloquear else ("CONFIRM" if debe_confirmar else "PASSES")
        real = "BLOCKS" if b else ("CONFIRM" if d else "PASSES")
        correcto = (esperado == real)

    marca = "OK  " if correcto else "FAIL"
    if not correcto:
        fallos.append((cmd, esperado, real, nota))
    print(f"{marca:<10} {cmd[:37]:<38} {real:<9} (expected {esperado})  {nota}")

print("\n" + "=" * 100)
print(f"RESULT: {len(CASOS) - len(fallos)}/{len(CASOS)} correct, {len(fallos)} failures")
print("=" * 100)
if fallos:
    print("\nCONFIRMED HOLES (command -> expected vs actual):")
    for cmd, esp, real, nota in fallos:
        print(f"  [{real} instead of {esp}] {cmd}")
        print(f"      {nota}")
sys.exit(1 if fallos else 0)