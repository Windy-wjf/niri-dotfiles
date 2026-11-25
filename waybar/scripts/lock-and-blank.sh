#!/bin/bash
# 锁屏包装：锁屏期间用独立的 swayidle 管理熄屏/点亮。
# - 无操作 10 秒 → 熄屏
# - 有活动 → 点亮
# 循环生效：点亮屏幕但不解锁，10 秒无操作后会再次熄屏。

BLANK_DELAY="${LOCK_BLANK_DELAY:-10}"

# 启动 swaylock（后台）
swaylock &
LOCK_PID=$!

# 锁屏期间专用的空闲管理：反复「无操作熄屏 → 活动点亮」
swayidle -w \
    timeout "$BLANK_DELAY" "niri msg action power-off-monitors" \
    resume "niri msg action power-on-monitors" &
IDLE_PID=$!

# 用户解锁（swaylock 退出）后清理专用 swayidle
wait "$LOCK_PID"
kill "$IDLE_PID" 2>/dev/null
