#!/usr/bin/env sh
# 换机器时运行：打印需要核对的硬件信息，方便修改配置
echo "== 显示器输出（niri，需会话已启动）=="
niri msg outputs 2>/dev/null || echo "niri 未运行或无法查询"

echo
echo "== DRM 显卡节点 =="
for c in /sys/class/drm/card[0-9]; do
    [ -e "$c" ] || continue
    printf '%s: ' "$(basename "$c")"
    cat "$c/device/vendor" "$c/device/device" 2>/dev/null | tr '\n' ' '
    echo
done

echo
echo "== 无线网卡 =="
ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -E '^(wl|wlan)' || echo "未找到 wl*/wlan* 网卡"

echo
echo "== DDC/CI 显示器（需 ddcutil）=="
if command -v ddcutil >/dev/null 2>&1; then
    ddcutil detect 2>/dev/null | grep -E 'Display|I2C bus|Model' | head -20 || echo "未检测到 DDC/CI 显示器"
else
    echo "未安装 ddcutil"
fi

echo
echo "== 字体 =="
fc-match 'CaskaydiaCove Nerd Font' 2>/dev/null | head -1 || echo "未安装字体"

echo
echo "== 主题 / 图标（需手动安装，仓库不含）=="
[ -d "$HOME/.themes/material-gnome-theme" ] && echo "GTK 主题: 已装" || echo "GTK 主题: 未装 (material-gnome-theme)"
[ -d "$HOME/.local/share/icons/WhiteSur" ] && echo "图标主题: 已装" || echo "图标主题: 未装 (WhiteSur)"

echo
echo "== 需要按结果修改的地方 =="
echo "  niri/config.kdl                     output 段：接口 / 分辨率 / 刷新率 / scale"
echo "  waybar/scripts/network_popup.py     IFACE = \"wlan0\""
echo "  waybar/scripts/vram.sh              card1"
echo "  waybar/scripts/brightness*.sh       DDC/CI 显示器与亮度步进"
