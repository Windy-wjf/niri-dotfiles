#!/usr/bin/env bash
# 监视 niri 配置文件，变动后自动重载，避免"改了配置没生效"。
# 由 systemd user 服务 niri-config-watch.service 常驻运行。

set -uo pipefail

CONFIG="$HOME/.config/niri/config.kdl"
LOG="/tmp/niri-config-watch.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

log "启动配置监视: $CONFIG"

while true; do
    # -q 静默；-e close_write 等写入完成后触发；--timeout 便于定期检查存活
    inotifywait -q -e close_write,moved_to,create "$CONFIG" 2>>"$LOG" || {
        sleep 2
        continue
    }
    # 等文件写入彻底完成
    sleep 0.4
    log "检测到配置变动，执行 reload"
    if niri msg action load-config-file >>"$LOG" 2>&1; then
        log "重载成功"
    else
        log "重载失败（niri 可能未运行）"
    fi
done
