#!/usr/bin/env bash
# 修复 FlClash「托盘图标在、代理在跑，但窗口消失且点图标打不开」的问题。
#
# 用法：
#   restore-flclash.sh          自动检测并修复（推荐）
#   restore-flclash.sh --force  强制重启（即使有窗口）
#
# 可绑定到快捷键，或在终端里直接运行。

set -euo pipefail

FORCE="${1:-}"
LOCK="$HOME/.local/share/com.follow.clash/FlClash.lock"

has_window() {
    niri msg -j windows 2>/dev/null | python3 -c '
import json, sys
try:
    wins = json.load(sys.stdin)
    print("yes" if any(w.get("app_id") == "com.follow.clash" for w in wins) else "no")
except Exception:
    print("no")
'
}

# 无窗口但有进程 = 卡死状态；或者强制重启
if [ "$FORCE" != "--force" ] && [ "$(has_window)" = "yes" ]; then
    echo "FlClash 窗口正常，无需修复。"
    exit 0
fi

if [ "$(has_window)" = "yes" ]; then
    state="有窗口(强制重启)"
else
    state="窗口丢失"
fi
echo "检测：$state"

# 先结束所有 flclash 主进程（SIGTERM 对 Flutter 无效，直接 SIGKILL）
if pgrep -x flclash >/dev/null 2>&1; then
    echo "结束卡死的 flclash 进程..."
    pkill -9 -x flclash || true
    sleep 1.5
fi

# 清掉单实例锁，否则新进程会认为已有实例而退出
rm -f "$LOCK"

echo "重新启动 flclash..."
niri msg action spawn-sh -- "flclash"

# 最多等 12 秒确认窗口出现
for _ in $(seq 1 12); do
    sleep 1
    if [ "$(has_window)" = "yes" ]; then
        echo "✓ FlClash 窗口已恢复。"
        exit 0
    fi
done

echo "✗ 窗口仍未出现，请检查 flclash 运行状态。" >&2
exit 1
