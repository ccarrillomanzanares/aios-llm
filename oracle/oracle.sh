#!/usr/bin/env bash
# =============================================================================
# oracle.sh — Banco de pruebas de AIOS sobre el VPS, sin VMs ni KVM
#
# Un rootfs de AIOS extraido de la ISO publicada, montado en SOLO LECTURA, con
# una capa de escritura desechable encima (overlayfs). Los comandos corren
# dentro, en su propio namespace PID/UTS, para que `ps` y `hostname` no mientan.
#
#   oracle.sh setup      monta el oraculo
#   oracle.sh run -- CMD ejecuta CMD dentro de AIOS
#   oracle.sh reset      devuelve el oraculo a limpio
#   oracle.sh verify     comprueba que el oraculo es INTEGRO (base sin tocar)
#   oracle.sh teardown   desmonta todo
#   oracle.sh status     estado
#
# DISENO ANTIFALLOS (cada uno responde a un fallo real observado)
#   1. El BASE se monta en solo lectura sobre si mismo ANTES del overlay. Da
#      igual si el overlay falla: el base no se puede escribir. Sin esto, un
#      reset fallido escribe en el arbol bueno y contamina la linea base.
#   2. `run` RECHAZA ejecutar si el overlay no esta montado. Un chroot sobre el
#      directorio desnudo se ejecuta igual y no avisa: las escrituras se
#      escapan. Preferimos fallar a envenenar datos.
#   3. `reset` y `setup` VERIFICAN el montaje y abortan si no cuelga.
#   4. /run y /tmp son tmpfs NUEVOS dentro del oraculo, no los del VPS. Montar
#      el /run del VPS dejaba al descubierto su socket de D-Bus.
#
# FIDELIDAD — medido, no supuesto
#   REAL     : sven (install/remove/search/list/info/path) y su base de datos,
#              ficheros, /etc, permisos, la mayor parte de run_command.
#   SE NIEGA : systemctl -> "Running in chroot, ignoring command 'status'".
#              Falla honestamente: no envenena datos.
#   ARREGLADO: ps/top/lsof veian los procesos del VPS (281). Con namespace PID
#              ahora ven solo los suyos (3).
#              EFECTO SECUNDARIO, y su remedio: el mismo namespace hace que el
#              PID 1 sea nuestro bash, asi que sven detectaba "sysvinit" cuando
#              AIOS usa systemd. Se corrige creando /run/systemd/system en el
#              setup, que es lo que consultan las herramientas. Arreglar una
#              mentira creo otra: por eso todo se comprueba despues, no antes.
#   RESIDUAL : free, df y uname -r siguen siendo datos del VPS. Quien los lea
#              tiene que saberlo.
#   NO SIRVE : escritorio y navegador. i3/Xorg/xdotool/scrot/chromium estan en
#              el arbol pero sin DISPLAY real. Eso se prueba en hierro real.
# =============================================================================
set -euo pipefail

ROOT="${ORACLE_ROOT:-/srv/oracle}"
BASE="$ROOT/base"
UPPER="$ROOT/upper"
WORK="$ROOT/work"
MERGED="$ROOT/merged"
CANARIO="$ROOT/.canario"          # fichero testigo para detectar escrituras al base

log()  { printf '\033[1;36m[oraculo]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  AVISO\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[oraculo:ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

_umount_if() { mountpoint -q "$1" 2>/dev/null && umount -R "$1" 2>/dev/null || true; }

# OJO con el formato: /proc/mounts escribe
#     <dispositivo> <punto> <tipo> <opciones> ...
# mientras que el comando `mount` escribe "A on B type C". Buscar el texto
# "on X type Y" en /proc/mounts NO encuentra nada nunca: el guardian decia que
# el overlay no estaba montado cuando SI lo estaba. Se compara por campos.
_montado_como() {   # $1 = punto de montaje, $2 = tipo (opcional)
  if [ -n "${2:-}" ]; then
    awk -v m="$1" -v t="$2" '$2==m && $3==t{f=1} END{exit !f}' /proc/mounts
  else
    awk -v m="$1" '$2==m{f=1} END{exit !f}' /proc/mounts
  fi
}

_es_ro() { awk -v m="$1" '$2==m && $4 ~ /(^|,)ro(,|$)/{f=1} END{exit !f}' /proc/mounts; }

# El base en solo lectura sobre si mismo: la red de seguridad principal.
_base_ro() {
  if ! mountpoint -q "$BASE"; then
    mount --bind "$BASE" "$BASE"
    mount -o remount,ro,bind "$BASE"
  fi
  mountpoint -q "$BASE" || die "no pude montar el base en solo lectura"
  _es_ro "$BASE" && return 0
  warn "no confirmo que $BASE este en ro; revisa /proc/mounts"
}

_overlay_montado() { _montado_como "$MERGED" overlay; }

cmd_setup() {
  [ -d "$BASE" ] || die "no existe $BASE (extrae el rootfs de la ISO primero)"
  [ -e "$BASE/usr/sbin/sven" ] || [ -e "$BASE/usr/bin/sven" ] \
    || die "$BASE no parece un rootfs de AIOS"

  mkdir -p "$UPPER" "$WORK" "$MERGED"
  _base_ro

  _overlay_montado && log "overlay ya estaba montado"
  _overlay_montado || {
    log "montando overlay (base ro + capa desechable)"
    mount -t overlay overlay \
      -o "lowerdir=$BASE,upperdir=$UPPER,workdir=$WORK" "$MERGED" \
      || die "mount -t overlay fallo"
  }
  _overlay_montado || die "el overlay no quedo montado: NO se ejecuta nada asi"

  log "montando pseudo-ficherosystems"
  # proc/sys/dev vienen del VPS (necesarios); run y tmp son NUEVOS
  for m in proc sys dev dev/pts; do
    mkdir -p "$MERGED/$m"
    mountpoint -q "$MERGED/$m" || mount --bind "/$m" "$MERGED/$m"
  done
  for m in run tmp; do
    mkdir -p "$MERGED/$m"
    mountpoint -q "$MERGED/$m" || mount -t tmpfs -o mode=755,size=512m tmpfs "$MERGED/$m"
  done

  # Marcador de systemd. AIOS usa systemd, pero dentro del namespace PID el
  # PID 1 es nuestro bash: las herramientas que detectan el init (sven entre
  # ellas) concluyen "sysvinit" y se equivocan. Este directorio es lo que
  # consultan. Sin el, sven MIENTE sobre el init del sistema.
  mkdir -p "$MERGED/run/systemd/system" "$MERGED/run/systemd/private" \
           "$MERGED/run/systemd/seats" "$MERGED/run/systemd/users"
  mkdir -p "$MERGED/etc/systemd/system" 2>/dev/null || true

  # DNS: el rootfs trae el stub de systemd-resolved, que aqui no existe
  [ -s "$MERGED/etc/resolv.conf" ] || cp /etc/resolv.conf "$MERGED/etc/resolv.conf"

  _overlay_montado || die "el overlay desaparecio tras montar los pseudo-fs"
  # canario: si alguien escribe al base, esto lo delata
  [ -e "$CANARIO" ] || : > "$CANARIO"
  ok "oraculo montado y verificado"
}

cmd_run() {
  [ "${1:-}" = "--" ] && shift
  [ $# -gt 0 ] || die "uso: oracle.sh run -- COMANDO [args]"
  _overlay_montado || die "el overlay NO esta montado. Escribir ahora escaparia al arbol base. Ejecuta: oracle.sh setup"

  unshare --pid --uts --fork --mount-proc="$MERGED/proc" \
    chroot "$MERGED" /bin/bash -c "
      export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
      export HOME=/root TERM=dumb
      hostname aios-oraculo 2>/dev/null || true
      cd /root 2>/dev/null || cd /
      $*
    "
}

cmd_reset() {
  _overlay_montado || { log "no montado; nada que resetear"; cmd_setup >/dev/null; return 0; }
  log "reseteando"
  for m in tmp run dev/pts dev sys proc; do _umount_if "$MERGED/$m"; done
  _umount_if "$MERGED"
  _overlay_montado && die "no pude desmontar el overlay; no reseteo a ciegas"
  rm -rf "${UPPER:?}"/* "${WORK:?}"/*
  cmd_setup >/dev/null
  _overlay_montado || die "el reset no dejo el overlay montado"
  ok "reset hecho y verificado (capa de escritura vacia)"
}

cmd_teardown() {
  for m in tmp run dev/pts dev sys proc; do _umount_if "$MERGED/$m"; done
  _umount_if "$MERGED"
  _umount_if "$BASE"
  log "desmontado"
}

# La prueba que importa: ¿el base sigue sin tocar?
cmd_verify() {
  local fallos=0
  echo "=== INTEGRIDAD DEL ORACULO ==="

  if mountpoint -q "$BASE"; then ok "base montado en solo lectura"; else warn "base NO esta montado en ro"; fallos=$((fallos+1)); fi
  if _overlay_montado; then ok "overlay montado"; else warn "overlay NO montado"; fallos=$((fallos+1)); fi

  echo -n "  escrituras al base: "
  if [ -w "$BASE/" ]; then
    ( echo test > "$BASE/.prueba_escritura" ) 2>/dev/null \
      && { warn "EL BASE ES ESCRIBIBLE. Grupo, no oraculo."; rm -f "$BASE/.prueba_escritura"; fallos=$((fallos+1)); } \
      || ok "rechaza escrituras"
  else
    ok "rechaza escrituras"
  fi

  echo -n "  ficheros en la capa de escritura: "
  local n; n=$(find "$UPPER" -type f 2>/dev/null | wc -l)
  echo "$n"
  if [ "$n" -eq 0 ]; then ok "capa limpia"; else warn "capa con $n ficheros (hay dano sin resetear)"; fi

  echo -n "  sven responde: "
  if cmd_run -- 'sven version' >/dev/null 2>&1; then ok "si"; else warn "no"; fallos=$((fallos+1)); fi

  echo -n "  init que detecta sven (debe decir systemd): "
  local ini; ini=$(cmd_run -- 'sven version 2>&1 | grep -oE "systemd|sysvinit|openrc" | head -1' 2>/dev/null || echo "?")
  echo "$ini"
  [ "$ini" = "systemd" ] && ok "init correcto" || warn "sven detecta '$ini' y deberia ser systemd: revisa /run/systemd/system"

  echo -n "  procesos que ve ps (debe ser <10): "
  local p; p=$(cmd_run -- 'ps -e --no-headers 2>/dev/null | wc -l' 2>/dev/null || echo "?")
  echo "$p"
  if [ "$p" != "?" ] && [ "$p" -lt 10 ]; then ok "namespace PID aislado"; else warn "ps ve demasiado: el aislamiento falla"; fallos=$((fallos+1)); fi

  echo
  [ "$fallos" -eq 0 ] && { ok "ORACULO INTEGRO"; return 0; } || { warn "$fallos comprobacion(es) fallidas"; return 1; }
}

cmd_status() {
  echo "ROOT    : $ROOT"
  echo "base    : $(du -sh "$BASE" 2>/dev/null | cut -f1)  ($BASE)"
  echo "overlay : $(_overlay_montado && echo MONTADO || echo 'NO montado')"
  echo "upper   : $(find "$UPPER" -type f 2>/dev/null | wc -l) ficheros"
  _overlay_montado && { echo -n "sven    : "; cmd_run -- 'sven version 2>&1 | grep -oE "SVEN  v[0-9.]+" | head -1' || echo "no responde"; }
}

case "${1:-}" in
  setup)    cmd_setup ;;
  run)      shift; cmd_run "$@" ;;
  reset)    cmd_reset ;;
  verify)   cmd_verify ;;
  teardown) cmd_teardown ;;
  status)   cmd_status ;;
  *) cat <<'TXT'
Uso: oracle.sh {setup|run -- CMD|reset|verify|teardown|status}

  setup        monta el oraculo (base en solo lectura + capa desechable)
  run -- CMD   ejecuta CMD dentro de AIOS
  reset        devuelve el oraculo a limpio
  verify       comprueba que el base sigue sin tocar  <-- ejecutar a menudo
  teardown     desmonta todo
  status       estado
TXT
  ;;
esac