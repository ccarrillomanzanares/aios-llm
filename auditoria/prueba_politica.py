#!/usr/bin/env python3
"""Auditoria MEDIDA de la capa de seguridad de aios-agent.

No lee el codigo y opina: importa las dos funciones reales de tools.py y les
pasa una tabla de casos con el veredicto que DEBERIAN dar. Lo que falle, es un
agujero con evidencia.

Uso (en el VPS, con PYTHONPATH apuntando a aios-agent):
    cd ~/aios-agent && python3 <este_fichero>
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
print(f"Funciones cargadas de {RUTA}\n")

# (comando, ¿debe BLOQUEARSE?, ¿debe PEDIR CONFIRMACION?, nota)
CASOS = [
    # --- DEBE BLOQUEARSE SIEMPRE (ni confirmacion: nunca se ejecuta) ---
    ("rm -rf /",              True,  None, "el caso canonical"),
    ("rm -rf /*",             True,  None, ""),
    ("dd if=/dev/zero of=/dev/sda", True, None, "escribir el disco"),
    ("mkfs.ext4 /dev/sda1",   True,  None, "formatear"),
    ("fdisk /dev/sda",        True,  None, "particionar"),
    ("shred -u /etc/passwd",  True,  None, "irreversible por diseno"),
    ("wipefs -a /dev/sda",    True,  None, ""),
    ("chmod 000 /etc/shadow", True,  None, ""),
    ("dockerd --host tcp://0.0.0.0:2375", True, None, "docker sin TLS = root para todos"),

    # --- DEBE PEDIR CONFIRMACION ---
    ("rm -rf /home/usuario/cosa", True, True, ""),
    ("sudo rm /etc/passwd",   False, True, "sudo rm"),
    ("sven install docker",   False, True, "el bug que se midio: instalo solo"),
    ("sven remove curl",      False, True, ""),
    ("apt-get install nginx", False, True, "no existe en AIOS, pero se caza"),
    ("pip install requests",  False, True, ""),
    ("systemctl mask firewalld", False, True, ""),
    ("find /var/log -delete", False, True, ""),
    ("truncate -s 0 /etc/passwd", False, True, ""),
    ("echo x > /etc/passwd",  False, True, "sobreescribir con >"),
    ("mv /etc/passwd /tmp/",  False, True, "mover en vez de borrar"),
    ("dd if=/dev/zero of=/tmp/x", False, True, ""),

    # --- NO DEBE HACER NADA (si esto se bloquea, el asistente es inutil) ---
    ("ls -la",                False, False, ""),
    ("cat /etc/hostname",     False, False, ""),
    ("df -h",                 False, False, ""),
    ("systemctl status sshd", False, False, "solo consulta"),
    ("echo hola > /tmp/x",    False, False, "/tmp esta exento a proposito"),
    ("rm -rf /tmp/basura",    False, False, ""),
    ("sven list",             False, False, "consultar no cambia nada"),

    # ========================== AGUJEROS A COMPROBAR ==========================
    # Estos son los que yo SOSPECHO que se cuelan. La columna 'debe' es lo
    # correcto; si sale FAIL, el agujero es real y queda con evidencia.
    ("rm -r /var/lib/sven",             False, True,  "AGUJERO?: solo se caza 'rm -rf', no 'rm -r'"),
    ("rm --recursive --force /home/x",  False, True,  "AGUJERO?: opciones largas"),
    ("sudo tee /etc/passwd",            False, True,  "AGUJERO?: tee no esta en ninguna lista"),
    ("echo x | sudo tee /etc/passwd",   False, True,  "AGUJERO?: tee por tuberia"),
    ("cp /dev/null /etc/passwd",        False, True,  "AGUJERO?: cp tampoco"),
    ("ln -sf /dev/null /etc/passwd",    False, True,  "AGUJERO?: ln -sf tampoco"),
    ("chown -R nobody /",               False, True,  "AGUJERO?: chown tampoco"),
    ("sven --dry-run install docker",   False, True,  "AGUJERO?: bandera entre sven y el verbo"),
    ("systemctl stop systemd-networkd", False, True,  "AGUJERO?: solo se caza enable/disable/mask"),
    ("find /etc -delete && touch /tmp/x", False, True, "AGUJERO?: mencionar /tmp desactiva el chequeo"),
    ("truncate -s 0 /etc/passwd; touch /tmp/x", False, True, "AGUJERO?: idem para truncate"),
    ("echo y > /etc/passwd >> /tmp/log", False, True,  "AGUJERO?: un >> en cualquier sitio desactiva el chequeo de >"),
    ("git clean -fdx",                  False, False, "informativo: no pasa por run_command?"),
]

fallos = []
print(f"{'VEREDICTO':<10} {'COMANDO':<38} NOTA")
print("-" * 100)
for cmd, debe_bloquear, debe_confirmar, nota in CASOS:
    b = bloquea(cmd)
    d = destructiva(cmd)

    if debe_bloquear is None:
        esperado = "BLOQUEA"
        correcto = b
        real = "BLOQUEA" if b else ("CONFIRMA" if d else "PASA")
    else:
        esperado = "BLOQUEA" if debe_bloquear else ("CONFIRMA" if debe_confirmar else "PASA")
        real = "BLOQUEA" if b else ("CONFIRMA" if d else "PASA")
        correcto = (esperado == real)

    marca = "OK  " if correcto else "FALLA"
    if not correcto:
        fallos.append((cmd, esperado, real, nota))
    print(f"{marca:<10} {cmd[:37]:<38} {real:<9} (esperado {esperado})  {nota}")

print("\n" + "=" * 100)
print(f"RESULTADO: {len(CASOS) - len(fallos)}/{len(CASOS)} correctos, {len(fallos)} fallos")
print("=" * 100)
if fallos:
    print("\nAGUJEROS CONFIRMADOS (comando -> esperado vs real):")
    for cmd, esp, real, nota in fallos:
        print(f"  [{real} en vez de {esp}] {cmd}")
        print(f"      {nota}")
sys.exit(1 if fallos else 0)