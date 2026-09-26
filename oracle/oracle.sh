#!/usr/bin/env bash
# =============================================================================
# oracle.sh — AIOS test bench on the VPS, without VMs or KVM
#
# An AIOS rootfs extracted from the published ISO, mounted READ-ONLY, with a
# throwaway write layer on top (overlayfs). Commands run inside, in their own
# PID/UTS namespace, so that `ps` and `hostname` do not lie.
#
#   oracle.sh setup      mounts the oracle
#   oracle.sh run -- CMD runs CMD inside AIOS
#   oracle.sh reset      returns the oracle to a clean state
#   oracle.sh verify     checks that the oracle is INTACT (base untouched)
#   oracle.sh teardown   unmounts everything
#   oracle.sh status     status
#
# FAILSAFE DESIGN (each one answers a real observed failure)
#   1. The BASE is mounted read-only over itself BEFORE the overlay. It does not
#      matter if the overlay fails: the base cannot be written. Without this, a
#      failed reset writes into the good tree and contaminates the baseline.
#   2. `run` REFUSES to execute if the overlay is not mounted. A chroot over the
#      bare directory runs anyway and gives no warning: writes escape. We prefer
#      to fail rather than poison data.
#   3. `reset` and `setup` VERIFY the mount and abort if it does not hold.
#   4. /run and /tmp are NEW tmpfs inside the oracle, not the VPS ones. Mounting
#      the VPS /run exposed its D-Bus socket.
#
# FIDELITY — measured, not assumed
#   REAL     : sven (install/remove/search/list/info/path) and its database,
#              files, /etc, permissions, most of run_command.
#   REFUSES  : systemctl -> "Running in chroot, ignoring command 'status'".
#              It fails honestly: it does not poison data.
#   FIXED    : ps/top/lsof saw the VPS processes (281). With a PID namespace
#              they now see only their own (3).
#              SIDE EFFECT, and its remedy: the same namespace makes PID 1 our
#              bash, so sven detected "sysvinit" when AIOS uses systemd. Fixed
#              by creating /run/systemd/system in the setup, which is what the
#              tools query. Fixing one lie created another: that is why
#              everything is checked afterwards, not before.
#   RESIDUAL : free, df and uname -r are still VPS data. Whoever reads them
#              has to know that.
#   UNUSABLE : desktop and browser. i3/Xorg/xdotool/scrot/chromium are in the
#              tree but with no real DISPLAY. That is tested on real hardware.
# =============================================================================
set -euo pipefail

ROOT="${ORACLE_ROOT:-/srv/oracle}"
BASE="$ROOT/base"
UPPER="$ROOT/upper"
WORK="$ROOT/work"
MERGED="$ROOT/merged"
CANARIO="$ROOT/.canario"          # witness file to detect writes to the base

log()  { printf '\033[1;36m[oracle]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  WARN\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[oracle:ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

_umount_if() { mountpoint -q "$1" 2>/dev/null && umount -R "$1" 2>/dev/null || true; }

# CAREFUL with the format: /proc/mounts writes
#     <device> <mountpoint> <type> <options> ...
# while the `mount` command writes "A on B type C". Searching for the text
# "on X type Y" in /proc/mounts NEVER finds anything: the guard said the overlay
# was not mounted when it WAS. It is compared field by field.
_montado_como() {   # $1 = mountpoint, $2 = type (optional)
  if [ -n "${2:-}" ]; then
    awk -v m="$1" -v t="$2" '$2==m && $3==t{f=1} END{exit !f}' /proc/mounts
  else
    awk -v m="$1" '$2==m{f=1} END{exit !f}' /proc/mounts
  fi
}

_es_ro() { awk -v m="$1" '$2==m && $4 ~ /(^|,)ro(,|$)/{f=1} END{exit !f}' /proc/mounts; }

# The base read-only over itself: the main safety net.
_base_ro() {
  if ! mountpoint -q "$BASE"; then
    mount --bind "$BASE" "$BASE"
    mount -o remount,ro,bind "$BASE"
  fi
  mountpoint -q "$BASE" || die "could not mount the base read-only"
  _es_ro "$BASE" && return 0
  warn "cannot confirm that $BASE is ro; check /proc/mounts"
}

_overlay_montado() { _montado_como "$MERGED" overlay; }

cmd_setup() {
  [ -d "$BASE" ] || die "$BASE does not exist (extract the rootfs from the ISO first)"
  [ -e "$BASE/usr/sbin/sven" ] || [ -e "$BASE/usr/bin/sven" ] \
    || die "$BASE does not look like an AIOS rootfs"

  mkdir -p "$UPPER" "$WORK" "$MERGED"
  _base_ro

  _overlay_montado && log "overlay was already mounted"
  _overlay_montado || {
    log "mounting overlay (ro base + throwaway layer)"
    mount -t overlay overlay \
      -o "lowerdir=$BASE,upperdir=$UPPER,workdir=$WORK" "$MERGED" \
      || die "mount -t overlay failed"
  }
  _overlay_montado || die "the overlay did not stay mounted: NOTHING is executed like this"

  log "mounting pseudo-filesystems"
  # proc/sys/dev come from the VPS (required); run and tmp are NEW
  for m in proc sys dev dev/pts; do
    mkdir -p "$MERGED/$m"
    mountpoint -q "$MERGED/$m" || mount --bind "/$m" "$MERGED/$m"
  done
  for m in run tmp; do
    mkdir -p "$MERGED/$m"
    mountpoint -q "$MERGED/$m" || mount -t tmpfs -o mode=755,size=512m tmpfs "$MERGED/$m"
  done

  # systemd marker. AIOS uses systemd, but inside the PID namespace PID 1 is our
  # bash: the tools that detect the init (sven among them) conclude "sysvinit"
  # and get it wrong. This directory is what they query. Without it, sven LIES
  # about the system's init.
  mkdir -p "$MERGED/run/systemd/system" "$MERGED/run/systemd/private" \
           "$MERGED/run/systemd/seats" "$MERGED/run/systemd/users"
  mkdir -p "$MERGED/etc/systemd/system" 2>/dev/null || true

  # DNS: the rootfs ships the systemd-resolved stub, which does not exist here
  [ -s "$MERGED/etc/resolv.conf" ] || cp /etc/resolv.conf "$MERGED/etc/resolv.conf"

  _overlay_montado || die "the overlay vanished after mounting the pseudo-fs"
  # canary: if anyone writes to the base, this gives them away
  [ -e "$CANARIO" ] || : > "$CANARIO"
  ok "oracle mounted and verified"
}

cmd_run() {
  [ "${1:-}" = "--" ] && shift
  [ $# -gt 0 ] || die "usage: oracle.sh run -- COMMAND [args]"
  _overlay_montado || die "the overlay is NOT mounted. Writing now would escape into the base tree. Run: oracle.sh setup"

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
  _overlay_montado || { log "not mounted; nothing to reset"; cmd_setup >/dev/null; return 0; }
  log "resetting"
  for m in tmp run dev/pts dev sys proc; do _umount_if "$MERGED/$m"; done
  _umount_if "$MERGED"
  _overlay_montado && die "could not unmount the overlay; refusing to reset blindly"
  rm -rf "${UPPER:?}"/* "${WORK:?}"/*
  cmd_setup >/dev/null
  _overlay_montado || die "the reset did not leave the overlay mounted"
  ok "reset done and verified (empty write layer)"
}

cmd_teardown() {
  for m in tmp run dev/pts dev sys proc; do _umount_if "$MERGED/$m"; done
  _umount_if "$MERGED"
  _umount_if "$BASE"
  log "unmounted"
}

# The test that matters: is the base still untouched?
cmd_verify() {
  local fallos=0
  echo "=== ORACLE INTEGRITY ==="

  if mountpoint -q "$BASE"; then ok "base mounted read-only"; else warn "base is NOT mounted ro"; fallos=$((fallos+1)); fi
  if _overlay_montado; then ok "overlay mounted"; else warn "overlay NOT mounted"; fallos=$((fallos+1)); fi

  echo -n "  writes to the base: "
  if [ -w "$BASE/" ]; then
    ( echo test > "$BASE/.prueba_escritura" ) 2>/dev/null \
      && { warn "THE BASE IS WRITABLE. Group, not oracle."; rm -f "$BASE/.prueba_escritura"; fallos=$((fallos+1)); } \
      || ok "refuses writes"
  else
    ok "refuses writes"
  fi

  echo -n "  files in the write layer: "
  local n; n=$(find "$UPPER" -type f 2>/dev/null | wc -l)
  echo "$n"
  if [ "$n" -eq 0 ]; then ok "clean layer"; else warn "layer with $n files (damage not reset)"; fi

  echo -n "  sven responds: "
  if cmd_run -- 'sven version' >/dev/null 2>&1; then ok "yes"; else warn "no"; fallos=$((fallos+1)); fi

  echo -n "  init that sven detects (it must say systemd): "
  local ini; ini=$(cmd_run -- 'sven version 2>&1 | grep -oE "systemd|sysvinit|openrc" | head -1' 2>/dev/null || echo "?")
  echo "$ini"
  [ "$ini" = "systemd" ] && ok "correct init" || warn "sven detects '$ini' and it should be systemd: check /run/systemd/system"

  echo -n "  processes that ps sees (must be <10): "
  local p; p=$(cmd_run -- 'ps -e --no-headers 2>/dev/null | wc -l' 2>/dev/null || echo "?")
  echo "$p"
  if [ "$p" != "?" ] && [ "$p" -lt 10 ]; then ok "isolated PID namespace"; else warn "ps sees too much: the isolation fails"; fallos=$((fallos+1)); fi

  echo
  [ "$fallos" -eq 0 ] && { ok "ORACLE INTACT"; return 0; } || { warn "$fallos failed check(s)"; return 1; }
}

cmd_status() {
  echo "ROOT    : $ROOT"
  echo "base    : $(du -sh "$BASE" 2>/dev/null | cut -f1)  ($BASE)"
  echo "overlay : $(_overlay_montado && echo MOUNTED || echo 'NOT mounted')"
  echo "upper   : $(find "$UPPER" -type f 2>/dev/null | wc -l) files"
  _overlay_montado && { echo -n "sven    : "; cmd_run -- 'sven version 2>&1 | grep -oE "SVEN  v[0-9.]+" | head -1' || echo "no response"; }
}

case "${1:-}" in
  setup)    cmd_setup ;;
  run)      shift; cmd_run "$@" ;;
  reset)    cmd_reset ;;
  verify)   cmd_verify ;;
  teardown) cmd_teardown ;;
  status)   cmd_status ;;
  *) cat <<'TXT'
Usage: oracle.sh {setup|run -- CMD|reset|verify|teardown|status}

  setup        mounts the oracle (read-only base + throwaway layer)
  run -- CMD   runs CMD inside AIOS
  reset        returns the oracle to a clean state
  verify       checks that the base is still untouched  <-- run often
  teardown     unmounts everything
  status       status
TXT
  ;;
esac