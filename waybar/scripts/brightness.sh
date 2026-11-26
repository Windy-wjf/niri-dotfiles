#!/usr/bin/env sh
# 自适应亮度控制：自动识别当前机器是笔记本（内屏背光）还是台式机（外接屏 DDC/CI）
#
#   brightness.sh          -> 输出当前亮度百分比（waybar 显示用）
#   brightness.sh up       -> 亮度 +5
#   brightness.sh down     -> 亮度 -5
#
# 检测逻辑：
#   1. 存在 /sys/class/backlight/*  -> 笔记本内屏，用 brightnessctl 直接读写
#   2. 否则                          -> 台式机外接屏，走 DDC/CI 守护进程
#                                       （由 niri 的 spawn-sh-at-startup 条件启动）

STEP=5
CACHE=/tmp/brightness.cache
FIFO=/tmp/brightness.fifo
PIDFILE=/tmp/brightness-daemon.pid
DAEMON=/home/wjf/.config/waybar/scripts/brightness-daemon.sh

has_backlight() {
  [ -d /sys/class/backlight ] && [ -n "$(ls -A /sys/class/backlight 2>/dev/null)" ]
}

# ---------- 笔记本内屏：brightnessctl ----------
backlight_get() {
  cur=$(brightnessctl get 2>/dev/null)
  max=$(brightnessctl max 2>/dev/null)
  if [ -n "$cur" ] && [ -n "$max" ] && [ "$max" -gt 0 ] 2>/dev/null; then
    printf '%s\n' $(( (cur * 100) / max ))
  fi
}

backlight_step() {
  if [ "$1" = up ]; then
    brightnessctl set "${STEP}%+"
  else
    brightnessctl set "${STEP}%-"
  fi >/dev/null 2>&1
}

# ---------- 台式机外接屏：DDC 守护进程 ----------
daemon_alive() {
  [ -f "$PIDFILE" ] || return 1
  pid=$(cat "$PIDFILE" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

ddc_send_event() {
  if ! daemon_alive; then
    [ -p "$FIFO" ] || { rm -f "$FIFO"; mkfifo "$FIFO"; }
    setsid "$DAEMON" >/dev/null 2>&1 </dev/null &
    i=0
    while [ "$i" -lt 20 ] && ! daemon_alive; do
      sleep 0.05
      i=$((i + 1))
    done
  fi
  timeout 1 sh -c 'printf "%s\n" "$1" > "$2"' sh "$1" "$FIFO" 2>/dev/null || true
}

ddc_get() {
  if [ -f "$CACHE" ]; then
    cat "$CACHE" 2>/dev/null
  else
    ddcutil getvcp 0x10 2>/dev/null | sed -n 's/.*current value = *\([0-9][0-9]*\).*/\1/p'
  fi
}

# ---------- 主逻辑 ----------
case "${1:-}" in
  up|down)
    if has_backlight; then
      backlight_step "$1"
    else
      ddc_send_event "$1"
    fi
    ;;
esac

if has_backlight; then
  v=$(backlight_get)
else
  v=$(ddc_get)
fi

[ -n "$v" ] && printf '%s%%\n' "$v" || printf -- '--\n'
