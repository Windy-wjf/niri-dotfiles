#!/usr/bin/env sh
# 笔记本内屏亮度控制（brightnessctl / intel_backlight）
# 用法：
#   brightness.sh          -> 输出当前亮度百分比（waybar 显示用）
#   brightness.sh up       -> 亮度 +5
#   brightness.sh down     -> 亮度 -5
#
# 与旧版（台式机 DDC/CI）不同，笔记本内屏走 /sys/class/backlight，
# 用 brightnessctl 直接读写，无需 ddcutil 守护进程和 FIFO。

get_brightness() {
  cur=$(brightnessctl get 2>/dev/null)
  max=$(brightnessctl max 2>/dev/null)
  if [ -n "$cur" ] && [ -n "$max" ] && [ "$max" -gt 0 ] 2>/dev/null; then
    printf '%s\n' $(( (cur * 100) / max ))
  fi
}

case "${1:-}" in
  up)
    brightnessctl set 5%+ >/dev/null 2>&1
    ;;
  down)
    brightnessctl set 5%- >/dev/null 2>&1
    ;;
esac

v=$(get_brightness)
[ -n "$v" ] && printf '%s%%\n' "$v" || printf -- '--\n'
