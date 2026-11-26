# niri-dotfiles

Arch Linux + [niri](https://github.com/YaLTeR/niri) 的个人桌面配置：4K 160Hz、2x 缩放、暗色半透明 waybar、fcitx5 中文输入。

## 功能

- **niri**：kitty 终端、fuzzel 启动器、Nautilus 文件管理器、swaylock 锁屏、中文快捷键帮助（`Super+/`）
- **waybar**（32px 高）：工作区、窗口标题、CPU / 内存 / 显存、网络、音量、外接显示器亮度、托盘、日期时间
- **网络悬浮窗**：点击网络图标打开 WiFi 列表，支持连接、断开、自动连接；点击空白处 / 再点图标 / ESC 关闭
- **亮度守护进程**：DDC/CI 控制外接显示器，FIFO 合并滚轮事件，避免 DDC 延迟导致的卡顿
- **显示设置面板**：点击状态栏显示器图标调整分辨率 / 刷新率 / 缩放倍率，可“保存为默认”写入 niri 配置
- **fcitx5**：中文输入环境变量与配置
- **fuzzel**：与 waybar 一致的暗色主题
- **通知**：swaync 守护进程 + 状态栏通知按钮（左键切换通知中心，右键切换勿扰）
- **电源菜单**：状态栏最右电源图标点击弹出小窗口，含锁屏 / 登出 / 关机 / 重启（关机和重启需二次确认）
- **锁屏**：电源菜单中的锁屏项 + `Super+Alt+L` 快捷键；`swayidle` 空闲 5 分钟自动锁屏、10 分钟息屏；`swaylock` 用暗化模糊壁纸和 Catppuccin 配色
- **WPS 兼容**：niri 不内置 XWayland，用 `xwayland-satellite` 提供 X11；`wps-desktop/` 里的用户级 desktop 覆盖显式设置 `DISPLAY=:0`、`QT_QPA_PLATFORM=xcb` 并清除 `WAYLAND_DISPLAY`，使 WPS 走 X11 而不崩溃，Nautilus 双击 doc/pdf 等文件可正常打开
- **设置面板**（状态栏最右齿轮 ``）：一个面板两个标签页
  - 「状态栏模块」：勾选要显示的模块；拖动每行左侧 `☰` 把手调整顺序（保持原区域）；应用后写回 `config.jsonc` 并重载 waybar（自动备份）
  - 「显示设置」：分辨率 / 刷新率 / 缩放，可保存为默认写入 niri 配置
- **壁纸**：`swaybg` 在 Background 层铺暗色月球壁纸（图片已包含在 `assets/`）；可用图形工具 **Azote**（`Super+D` 搜索 "Azote" 启动）交互式更换壁纸和填充模式

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
waybar/scripts/display_settings_popup.py  # GTK 显示设置面板（备用，当前未挂在状态栏）
waybar/scripts/waybar_settings_popup.py  # 设置面板：模块开关 + 显示设置（齿轮按钮）
waybar/scripts/power_menu.py            # 电源菜单：锁屏 / 登出 / 关机 / 重启
fuzzel/fuzzel.ini               # fuzzel 暗色主题
fcitx5/                         # fcitx5 配置
environment.d/input-method.conf # niri 会话的输入法环境变量
environment.d/xwayland.conf     # DISPLAY=:0，供 X11 程序（WPS 等）使用
wps-desktop/                    # WPS desktop 覆盖（补 DISPLAY），安装到 ~/.local/share/applications/
swaylock/config                 # 锁屏外观（壁纸/配色/指示器）
swayidle/config                 # 空闲锁屏与息屏时间
install.sh                      # 安装脚本
machine-check.sh                # 换机器时检测硬件并提示需要改的配置
mimeapps.list                   # 默认应用关联
assets/wallhaven-5yk9o1.png     # 壁纸图片（暗色月球）
```

## 依赖

```bash
sudo pacman -S --needed \
  niri waybar kitty fuzzel swaylock swaybg azote wlr-randr \
  fcitx5 fcitx5-chinese-addons \
  polkit-gnome networkmanager wireplumber playerctl swaync xwayland-satellite \
  swaylock swayidle imagemagick \
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
- 系统级默认应用 `mimeapps.list` 已包含在仓库里，安装脚本会一并复制。壁纸图片在 `assets/`，安装脚本会复制到 `~/Pictures/`，并把配置里的 `/home/wjf/Pictures/...` 路径改写成当前家目录。

## 换机器迁移清单

`install.sh` 会把配置里的 `/home/wjf` 改写成当前用户的家目录，但下面这些跟硬件/桌面环境绑定，需要按新机器核对（可先运行 `./machine-check.sh` 查看检测结果）：

1. **显示器**：`niri/config.kdl` 的 `output "DP-1" { mode "3840x2160@160.000"; scale 2; }` 改成新机器的接口、分辨率、刷新率和缩放。
2. **无线网卡**：`waybar/scripts/network_popup.py` 的 `IFACE = "wlan0"` 改成实际网卡名。
3. **显卡**：`waybar/scripts/vram.sh` 读的是 `card1`，按新机器的 DRM 节点调整。
4. **亮度**：`brightness*.sh` 依赖 ddcutil 和支持 DDC/CI 的外接显示器；笔记本内屏请改用 backlight / brightnessctl。
5. **外观**（仓库不含这些大文件）：
   - 安装 GTK 主题 `material-gnome-theme`（放到 `~/.themes/`）和图标 `WhiteSur`（放到 `~/.local/share/icons/`）；
   - 执行一次：
     ```sh
     gsettings set org.gnome.desktop.interface gtk-theme material-gnome-theme
     gsettings set org.gnome.desktop.interface icon-theme WhiteSur
     gsettings set org.gnome.desktop.interface color-scheme prefer-dark
     ```
6. **会话**：这台机器由 GDM 拉起 `niri-session`；新机器装好 niri 后在 GDM 选 niri 会话即可。

按上面 6 步调整后，快捷键、状态栏、网络弹窗、亮度守护进程、输入法等的布局和体验就能和这台机器一致。
