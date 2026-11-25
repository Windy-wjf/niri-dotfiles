#!/bin/bash
# 锁屏包装：启动 swaylock，10 秒后若仍在锁屏状态则关闭显示器。
# 这样无论自动锁屏（swayidle）还是手动锁屏（快捷键/电源菜单）行为一致。
# 若在 10 秒内解锁，则不会熄屏。

BLANK_DELAY="${LOCK_BLANK_DELAY:-10}"

# 启动 swaylock（后台），记录 PID
swaylock &
LOCK_PID=$!

# 后台等待：到点后检查 swaylock 是否仍在运行，是则熄屏
(
    sleep "$BLANK_DELAY"
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        niri msg action power-off-monitors >/dev/null 2>&1
    fi
) &

# 等待 swaylock 退出（用户解锁）
wait "$LOCK_PID"
