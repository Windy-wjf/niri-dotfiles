#!/usr/bin/env bash
# 安装 niri + waybar + fuzzel + fcitx5 配置到当前用户
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/niri-dotfiles-backup-$STAMP"

echo "源目录:   $SRC"
echo "目标目录: $DEST"

mkdir -p "$DEST" "$BACKUP"

for rel in niri waybar fuzzel fcitx5 environment.d mimeapps.list; do
    if [ -e "$DEST/$rel" ]; then
        mkdir -p "$BACKUP/$(dirname "$rel")"
        cp -a "$DEST/$rel" "$BACKUP/$rel"
        echo "已备份: $DEST/$rel -> $BACKUP/$rel"
    fi
done

mkdir -p "$DEST"/{niri,waybar/scripts,fuzzel,fcitx5/conf,environment.d}
cp -a "$SRC/niri/config.kdl" "$DEST/niri/"
cp -a "$SRC/waybar/config.jsonc" "$SRC/waybar/style.css" "$SRC/waybar/wifibar.py" "$DEST/waybar/"
cp -a "$SRC/waybar/scripts/." "$DEST/waybar/scripts/"
cp -a "$SRC/fuzzel/fuzzel.ini" "$DEST/fuzzel/"
cp -a "$SRC/fcitx5/config" "$SRC/fcitx5/profile" "$DEST/fcitx5/"
cp -a "$SRC/fcitx5/conf/." "$DEST/fcitx5/conf/"
cp -a "$SRC/environment.d/input-method.conf" "$DEST/environment.d/"
cp -a "$SRC/environment.d/xwayland.conf" "$DEST/environment.d/"
cp -a "$SRC/mimeapps.list" "$DEST/mimeapps.list"

# 修复 WPS 在 niri（纯 Wayland）下启动：显式指定 xwayland-satellite 提供的 DISPLAY
if [ -d "$SRC/wps-desktop" ]; then
    mkdir -p "$HOME/.local/share/applications"
    cp -a "$SRC"/wps-desktop/*.desktop "$HOME/.local/share/applications/"
fi

# swaylock 外观 + swayidle 空闲锁屏
mkdir -p "$DEST/swaylock" "$DEST/swayidle"
cp -a "$SRC/swaylock/config" "$DEST/swaylock/"
cp -a "$SRC/swayidle/config" "$DEST/swayidle/"

mkdir -p "$HOME/Pictures"
cp -a "$SRC/assets/wallhaven-5yk9o1.png" "$HOME/Pictures/"
# 生成锁屏用的暗化模糊壁纸（需要 ImageMagick）
if command -v magick >/dev/null 2>&1; then
    magick "$HOME/Pictures/wallhaven-5yk9o1.png" \
        -resize 2880x1800^ -gravity center -extent 2880x1800 \
        -blur 0x12 -fill '#181a24' -colorize 40 \
        -font /usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc \
        -pointsize 46 -fill '#cdd6f4' -gravity center \
        -annotate +0+320 '输入密码解锁' \
        "$HOME/Pictures/wallhaven-5yk9o1-lock.png"
elif command -v convert >/dev/null 2>&1; then
    convert "$HOME/Pictures/wallhaven-5yk9o1.png" \
        -resize 2880x1800^ -gravity center -extent 2880x1800 \
        -blur 0x12 -fill '#181a24' -colorize 40 \
        -font /usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc \
        -pointsize 46 -fill '#cdd6f4' -gravity center \
        -annotate +0+320 '输入密码解锁' \
        "$HOME/Pictures/wallhaven-5yk9o1-lock.png"
fi

chmod +x "$DEST/waybar/scripts/"*.sh "$DEST/waybar/scripts/"*.py 2>/dev/null || true

if [ "$HOME" != "/home/wjf" ]; then
    while IFS= read -r f; do
        sed -i "s|/home/wjf|$HOME|g" "$f"
        echo "已改写路径: $f"
    done < <(grep -rl '/home/wjf' \
        "$DEST/niri/config.kdl" \
        "$DEST/waybar/config.jsonc" \
        "$DEST/waybar/scripts/brightness.sh" \
        "$DEST/swaylock/config" \
        "$DEST/swayidle/config" 2>/dev/null || true)
fi

cat <<EOF

安装完成。
原配置备份: $BACKUP

接下来：
  1. 运行仓库里的 ./machine-check.sh，并按 README 的“换机器迁移清单”核对硬件相关配置
  2. 确认依赖已安装（见 README.md）
  3. 注销并重新登录 niri 会话
  4. 按 Super+/ 查看快捷键

注意：如果显示器不是 DP-1 / 3840x2160@160，请先修改
  $DEST/niri/config.kdl 里的 output 段。
EOF
