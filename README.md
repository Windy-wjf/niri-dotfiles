# niri-dotfiles

Arch Linux + [niri](https://github.com/YaLTeR/niri) 的个人桌面配置：4K 160Hz、2x 缩放、暗色半透明 waybar、fcitx5 中文输入。

## 功能

- **niri**：kitty 终端、fuzzel 启动器、Nautilus 文件管理器、swaylock 锁屏、中文快捷键帮助（`Super+/`）
- **waybar**（32px 高）：工作区、窗口标题、CPU / 内存 / 显存、网络、音量、外接显示器亮度、托盘、日期时间
- **网络悬浮窗**：点击网络图标打开 WiFi 列表，支持连接、断开、自动连接；点击空白处 / 再点图标 / ESC 关闭
- **亮度守护进程**：DDC/CI 控制外接显示器，FIFO 合并滚轮事件，避免 DDC 延迟导致的卡顿
- **fcitx5**：中文输入环境变量与配置
- **fuzzel**：与 waybar 一致的暗色主题

## 目录结构

```
niri/config.kdl                 # niri 主配置：输出、启动项、快捷键
waybar/config.jsonc             # waybar 模块布局
waybar/style.css                # waybar 样式（暗色半透明 + 圆角）
waybar/wifibar.py               # 旧版 WiFi 模块（pywayland + cairo，当前未启用）
waybar/scripts/clock.sh         # 日期 + 星期两行输出
waybar/scripts/vram.sh          # 独显显存占用
waybar/scripts/brightness.sh    # 亮度显示 / 发送 up-down 事件
waybar/scripts/brightness-daemon.sh  # DDC/CI 亮度守护进程
waybar/scripts/network_popup.py # GTK 网络悬浮窗
fuzzel/fuzzel.ini               # fuzzel 暗色主题
fcitx5/                         # fcitx5 配置
environment.d/input-method.conf # niri 会话的输入法环境变量
install.sh                      # 安装脚本
```

## 依赖

```bash
sudo pacman -S --needed \
  niri waybar kitty fuzzel swaylock \
  fcitx5 fcitx5-chinese-addons \
  polkit-gnome networkmanager wireplumber playerctl \
  ddcutil python-gobject gtk3 gtk-layer-shell python-pillow grim \
  ttf-cascadia-code-nerd ttf-nerd-fonts-symbols
```

可选：`nautilus`（`Super+E` 文件管理器）、`swaylock` 需要 `ext-session-lock`（niri 已支持）；未启用的 `wifibar.py` 另需 `python3-cairo`、`pywayland`。

## 安装

```bash
git clone git@github.com:Windy-wjf/niri-dotfiles.git
cd niri-dotfiles
./install.sh
```

安装脚本会：

1. 把现有配置备份到 `~/niri-dotfiles-backup-<时间>`；
2. 复制 `niri/`、`waybar/`、`fuzzel/`、`fcitx5/`、`environment.d/` 到 `~/.config`；
3. 如果当前用户不是 `/home/wjf`，自动把配置里的绝对路径改写成当前家目录；
4. 给 waybar 脚本加可执行权限。

安装后注销并重新登录 niri 会话即可。

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Super+/` | 显示快捷键帮助 |
| `Super+Return` | 打开终端 kitty |
| `Super+D` | 应用启动器 fuzzel |
| `Super+E` | 文件管理器 Nautilus |
| `Super+Alt+L` | 锁定屏幕 |
| `Super+O` | 切换总览 |
| `Super+Q` | 关闭窗口 |
| `Super+方向键` | 聚焦窗口 |
| `Super+Ctrl+方向键` | 移动列 / 窗口 |
| `Super+Page Up/Down` | 切换工作区 |
| `Super+Ctrl+Page Up/Down` | 移动列到工作区 |
| `Super+R` | 切换预设列宽 |
| `Super+F` | 最大化列 |
| `Super+Shift+F` | 全屏窗口 |
| `Super+V` | 切换窗口浮动 |
| `Super+W` | 切换列标签显示 |
| `Print` | 截图（niri 内置） |
| `Super+Shift+E` | 退出 niri |
| `Super+Shift+P` | 关闭显示器 |

## 需要按机器调整的地方

- `waybar/scripts/network_popup.py`：`IFACE = "wlan0"`，无线网卡名不同时修改。
- `waybar/scripts/vram.sh`：读取 `card1` 的显存，多显卡机器可能需要改成 `card0` 或按 PCI 地址定位。
- `waybar/scripts/brightness-daemon.sh`：`STEP=5` 为亮度步进；显示器需支持 DDC/CI（当前配置为 HKC G27H7Pro / DP-1）。
- `niri/config.kdl`：输出段为 `DP-1`、`3840x2160@160`、`scale 2`，换显示器需要修改。
- 状态栏高度 32px；网络弹窗位置会在打开时截图识别网络图标，自动跟随。
- `waybar/wifibar.py` 是早期基于 pywayland + cairo 的 WiFi 模块/悬浮菜单实现，依赖 `python3-cairo`、`pywayland`；当前 waybar 已改用内置 network 模块 + `scripts/network_popup.py`，该文件仅作参考保留。
- 系统级默认应用（`mimeapps.list`）和 GTK 主题不在本仓库内。
