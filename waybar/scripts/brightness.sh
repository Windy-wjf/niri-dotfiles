#!/usr/bin/env sh
# 外接显示器亮度控制（ddcutil，HKC G27H7Pro / DP-1）
# 用法：
#   brightness.sh          -> 输出当前亮度百分比（读缓存，waybar 显示用）
#   brightness.sh up       -> 亮度 +5（丢给守护进程，立即返回）
#   brightness.sh down     -> 亮度 -5（丢给守护进程，立即返回）
#
# 实际的 DDC/CI 读写由 brightness-daemon.sh 串行完成并合并突发滚动，
# 这里只负责发送事件和读取缓存，避免每个滚轮都排队等 DDC 往返。

CACHE=/tmp/brightness.cache
FIFO=/tmp/brightness.fifo
PIDFILE=/tmp/brightness-daemon.pid
DAEMON=/home/wjf/.config/waybar/scripts/brightness-daemon.sh

get_brightness() {
  ddcutil getvcp 0x10 2>/dev/null | sed -n 's/.*current value = *\([0-9][0-9]*\).*/\1/p'
}

daemon_alive() {
  [ -f "$PIDFILE" ] || return 1
  pid=$(cat "$PIDFILE" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

send_event() {
  if ! daemon_alive; then
    [ -p "$FIFO" ] || { rm -f "$FIFO"; mkfifo "$FIFO"; }
    setsid "$DAEMON" >/dev/null 2>&1 </dev/null &
    i=0
    while [ "$i" -lt 20 ] && ! daemon_alive; do
      sleep 0.05
      i=$((i + 1))
    done
  fi
  # 守护进程没起来时也不要卡住 waybar
  timeout 1 sh -c 'printf "%s\n" "$1" > "$2"' sh "$1" "$FIFO" 2>/dev/null || true
}

case "${1:-}" in
  up|down)
    send_event "$1"
    ;;
esac

if [ -f "$CACHE" ]; then
  v=$(cat "$CACHE" 2>/dev/null)
else
  v=$(get_brightness)
  [ -n "$v" ] && printf '%s\n' "$v" > "$CACHE" 2>/dev/null
fi

[ -n "$v" ] && printf '%s%%\n' "$v" || printf -- '--\n'
