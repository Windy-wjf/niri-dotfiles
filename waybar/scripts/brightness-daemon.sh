#!/usr/bin/env bash
# 外接显示器亮度守护进程（HKC G27H7Pro / DP-1）
# 内存中维护当前亮度，接收 FIFO 里的 up/down 事件，
# 合并突发滚动后一次性写入，避免每个滚轮都做一次耗时的 DDC/CI 往返。
set -u

CACHE=/tmp/brightness.cache
FIFO=/tmp/brightness.fifo
PIDFILE=/tmp/brightness-daemon.pid
LOCKFILE=/tmp/brightness-daemon.lock
LOG=/tmp/bright_scroll.log
STEP=5
QUIET_MS=90        # 多久没有新事件就认为这轮滚动结束
MAX_BATCH_MS=250   # 连续滚动时最长合并时间，保证亮度持续跟手

get_brightness() {
  ddcutil getvcp 0x10 2>/dev/null | sed -n 's/.*current value = *\([0-9][0-9]*\).*/\1/p'
}

# 单实例锁
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

[ -p "$FIFO" ] || { rm -f "$FIFO"; mkfifo "$FIFO"; }

cur=$(get_brightness)
[ -z "$cur" ] && cur=50
printf '%s\n' "$cur" > "$CACHE"
printf '%s\n' $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; exit 0' TERM INT

# 同时以读写方式打开 FIFO，保证 read 不会 EOF
exec 3<>"$FIFO"

while true; do
  if ! IFS= read -r -t 30 cmd <&3; then
    # 空闲 30 秒：与显示器实际值同步一次，避免用显示器 OSD 调过之后漂移
    actual=$(get_brightness)
    if [ -n "$actual" ] && [ "$actual" != "$cur" ]; then
      cur=$actual
      printf '%s\n' "$cur" > "$CACHE"
      pkill -SIGRTMIN+8 waybar 2>/dev/null
    fi
    continue
  fi

  delta=0
  case "$cmd" in
    up) delta=$STEP ;;
    down) delta=$((0 - STEP)) ;;
    *) continue ;;
  esac

  # 把紧跟其后的滚动事件合并进同一批
  start=${EPOCHREALTIME/./}
  while IFS= read -r -t 0.09 cmd2 <&3; do
    case "$cmd2" in
      up) delta=$((delta + STEP)) ;;
      down) delta=$((delta - STEP)) ;;
    esac
    now=${EPOCHREALTIME/./}
    [ $((now - start)) -ge $((MAX_BATCH_MS * 1000)) ] && break
  done

  new=$((cur + delta))
  [ "$new" -gt 100 ] && new=100
  [ "$new" -lt 0 ] && new=0

  ddcutil setvcp --noverify 0x10 "$new" >/dev/null 2>&1
  cur=$new
  printf '%s\n' "$cur" > "$CACHE"
  printf '%s %+d -> %s\n' "$(date '+%H:%M:%S')" "$delta" "$cur" >> "$LOG"

  # 通知 waybar 立刻重读缓存刷新数字
  pkill -SIGRTMIN+8 waybar 2>/dev/null
done
