#!/usr/bin/env python3
"""Bateria de NO-REGRESION de la capa de seguridad de aios-agent.

Se importan las funciones REALES de tools.py y se les pasa una tabla de casos con
el veredicto que deben dar. Este fichero es el CONTRATO de la capa: si algo
futuro rompe un caso, aparece aqui.

Uso (en el VPS):
    cd ~/aios-agent && PYTHONPATH=$HOME/aios-agent python3 <este_fichero>

Historia:
  26 Sep 2026  primera version  -> 27/41  (14 fallos, ver AUDITORIA)
  26 Sep 2026  tras las correcciones -> este fichero, 54 casos
"""
import importlib.util
import os
import sys

def _localizar_tools():
    """Encuentra tools.py: junto al script, en su directorio padre, o en ~/aios-agent."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    for c in (aqui, os.path.dirname(aqui), os.path.expanduser("~/aios-agent")):
        p = os.path.join(c, "tools.py")
        if os.path.isfile(p):
            return p
    raise SystemExit("No encuentro tools.py (probado: junto al script, su padre, ~/aios-agent)")


RUTA = _localizar_tools()
# tools.py importa sus hermanos (process, software_inventory...): su directorio
# tiene que estar en sys.path para que la bateria sea autonoma, sin PYTHONPATH.
sys.path.insert(0, os.path.dirname(RUTA))
spec = importlib.util.spec_from_file_location("aios_tools", RUTA)
m = importlib.util.module_from_spec(spec)
sys.modules["aios_tools"] = m
spec.loader.exec_module(m)

veredicto = m.verificar_comando
print("Bateria de la capa de seguridad de aios-agent")
print("Funciones cargadas de %s\n" % RUTA)

B, C, P = "BLOQUEA", "CONFIRMA", "PASA"

CASOS = [
    # ── 1. IRREVERSIBLE: no se ejecuta jamas, ni con permiso ──────────────────
    ("rm -rf /",                          B, "el caso canonico"),
    ("rm -rf /*",                         B, "antes se ESCAPABA al nivel de confirmacion"),
    ("rm -rf --no-preserve-root /",       B, ""),
    ("rm -rf /var/lib/docker",            B, ""),
    ("dd if=/dev/zero of=/dev/sda",       B, "escribir el disco"),
    ("mkfs.ext4 /dev/sda1",               B, "formatear"),
    ("fdisk /dev/sda",                    B, "particionar"),
    ("parted /dev/sda mklabel gpt",       B, "lo mismo por parted: NO estaba cubierto"),
    ("shred -u /etc/passwd",              B, "irreversible por diseno"),
    ("wipefs -a /dev/sda",                B, ""),
    ("chmod 000 /etc/shadow",             B, ""),
    ("dockerd --host tcp://0.0.0.0:2375", B, "docker sin TLS = root para todos"),

    # ── 2. EXIGE PERMISO ──────────────────────────────────────────────────────
    ("rm -rf /home/usuario/cosa",         C, "antes BLOQUEADO para siempre"),
    ("rm -rf /var/log/viejo",             C, "el defecto de uso que tenia: no se podia ni con permiso"),
    ("rm -rf build",                      C, "relativo: sigue pidiendo permiso, conservador"),
    ("rm -r /var/lib/sven",               C, "AGUJERO B1: solo se cazaba 'rm -rf'"),
    ("rm --recursive --force /home/x",    C, "AGUJERO B8: opciones largas"),
    ("sudo rm /etc/passwd",               C, ""),
    ("sudo tee /etc/passwd",              C, "AGUJERO B2: tee no estaba en ninguna lista"),
    ("echo x | sudo tee /etc/passwd",     C, "AGUJERO B2 por tuberia"),
    ("cp /dev/null /etc/passwd",          C, "AGUJERO B4"),
    ("ln -sf /dev/null /etc/passwd",      C, "AGUJERO B5"),
    ("chown -R nobody /",                 C, "AGUJERO B6"),
    ("sven install docker",               C, "el bug que origino la capa"),
    ("sven -y install docker",            C, "AGUJERO B3: bandera entre el verbo y el paquete"),
    ("sven --yes install docker",         C, "AGUJERO B3"),
    ("apt-get install nginx",             C, "no existe en AIOS, pero se caza"),
    ("apt-get -y install nginx",          C, ""),
    ("pip install requests",              C, ""),
    ("systemctl mask firewalld",          C, ""),
    ("systemctl disable sshd",            C, ""),
    ("systemctl stop systemd-networkd",   C, "AGUJERO B7: cortar la red en remoto"),
    ("systemctl restart sshd",            C, "AGUJERO B7: reiniciar lo que te da acceso"),
    ("find /var/log -delete",             C, ""),
    ("truncate -s 0 /etc/passwd",         C, ""),
    ("echo x > /etc/passwd",              C, "sobreescribir con >"),
    ("mv /etc/passwd /tmp/",              C, "mover en vez de borrar"),
    ("dd if=/dev/zero of=/tmp/x",         C, ""),

    # ── 3. BYPASS QUE ESTABAN ABIERTOS (errores de logica) ────────────────────
    ("find /etc -delete && touch /tmp/x",          C, "C1: mencionar /tmp desactivaba el chequeo"),
    ("truncate -s 0 /etc/passwd; touch /tmp/x",    C, "C1"),
    ("echo y > /etc/passwd >> /tmp/log",           C, "C2: un >> desactivaba el chequeo de >"),
    ("echo y >> /tmp/log > /etc/passwd",           C, "C2 en el otro orden"),
    ("rm -rf /var/log/viejo; touch /tmp/x",        C, "C1 aplicado a rm"),

    # ── 4. NO DEBE HACER NADA (si esto se bloquea, el asistente es inutil) ────
    ("ls -la",                            P, ""),
    ("cat /etc/hostname",                 P, "leer no es escribir"),
    ("df -h",                             P, ""),
    ("systemctl status sshd",             P, "solo consulta"),
    ("systemctl restart nginx",           P, "servicio normal: no corta el acceso"),
    ("fdisk -l /dev/sda",                 P, "FALSO POSITIVO corregido: -l solo LISTA"),
    ("parted -l",                         P, "FALSO POSITIVO corregido"),
    ("echo hola > /tmp/x",                P, "/tmp esta exento a proposito"),
    ("echo a >> /tmp/log",                P, ""),
    ("rm -rf /tmp/basura",                P, "la exencion de /tmp, que antes era inalcanzable"),
    ("sven list",                         P, "consultar no cambia nada"),
    ("cp /home/a /tmp/b",                 P, "destino fuera del sistema"),
    ("tee /home/usuario/notas.txt",       P, "destino fuera del sistema"),
    ("chmod -R 755 /home/usuario/proyecto", P, "recursivo pero sobre el home, no el sistema"),
]

fallos = []
anchos = max(len(c) for c, _, _ in CASOS)
print("%-8s %-*s %-9s %s" % ("MARCA", anchos, "COMANDO", "REAL", "NOTA"))
print("-" * 110)
for cmd, esperado, nota in CASOS:
    real, motivo = veredicto(cmd)
    real = {"bloquea": B, "confirma": C, "adelante": P}[real]
    ok = real == esperado
    if not ok:
        fallos.append((cmd, esperado, real, nota))
    print("%-8s %-*s %-9s %s" % ("OK" if ok else "FALLA", anchos, cmd, real,
                                 ("(esperado %s) " % esperado if not ok else "") + nota))

print("\n" + "=" * 110)
print("RESULTADO: %d/%d correctos, %d fallos" % (len(CASOS) - len(fallos), len(CASOS), len(fallos)))
print("=" * 110)
if fallos:
    print("\nFALLOS:")
    for cmd, esp, real, nota in fallos:
        print("  [%s en vez de %s] %s" % (real, esp, cmd))
        if nota:
            print("      %s" % nota)
sys.exit(1 if fallos else 0)
print("\nLa capa cumple su contrato. Cero fallos.")