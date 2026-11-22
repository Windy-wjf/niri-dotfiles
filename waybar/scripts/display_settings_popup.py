#!/usr/bin/env python3
"""Waybar 显示设置悬浮窗：分辨率、刷新率、缩放倍率。
点击 waybar 的显示器图标调用本脚本；再次点击图标、点空白、ESC 或移出关闭。
"""
import os
import re
import sys
import json
import time
import socket
import fcntl
import shutil
import subprocess
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

SOCKET_PATH = "/tmp/waybar-display-popup-%d.sock" % os.getuid()
LOCK_PATH = "/tmp/waybar-display-popup-%d.lock" % os.getuid()
BAR_HEIGHT = 32
POPUP_WIDTH = 440
POPUP_RIGHT_FALLBACK = 14
CONFIG_PATH = os.environ.get(
    "NIRI_CONFIG", os.path.expanduser("~/.config/niri/config.kdl")
)
SCALE_CHOICES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]


def run(args, timeout=6):
    try:
        p = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout,
        )
        return (p.returncode == 0, p.stdout.strip())
    except Exception as e:
        return (False, str(e))


def niri_outputs():
    ok, out = run(["niri", "msg", "-j", "outputs"])
    if not ok:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


def niri_output(name, args):
    return run(["niri", "msg", "output", name] + args)


def detect_display_right_edge(screen_width):
    """截取状态栏，找到显示设置图标（橙色 #fab387）的右边缘（逻辑像素）。"""
    try:
        from PIL import Image
    except Exception:
        return None

    tmp = "/tmp/waybar-display-bar.png"
    try:
        subprocess.run(
            ["grim", "-g", "0,0 %dx%d" % (screen_width, BAR_HEIGHT),
             "-s", "1", tmp],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=2,
        )
        im = Image.open(tmp).convert("RGB")
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    w, h = im.size
    pixels = im.load()
    cols = []
    for x in range(int(w * 0.60), w):
        for y in range(h):
            r, g, b = pixels[x, y]
            # #fab387 = (250, 179, 135)，与青色/黄色/粉色/紫色都区分开
            if (225 <= r <= 255 and 150 <= g <= 205 and 100 <= b <= 170
                    and r > g + 40 and g > b + 20):
                cols.append(x)
                break
    if not cols:
        return None
    return cols[-1]


class DisplayPopup(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.set_decorated(False)
        self.set_default_size(POPUP_WIDTH, 560)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        # niri 会把层 Shell 表面整体下移状态栏高度（exclusive zone），
        # 所以这里只留 8px 间隙，实际就是状态栏下方 8px
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 8)

        display = Gdk.Display.get_default()
        monitor = None
        if display is not None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        screen_width = monitor.get_geometry().width if monitor else 1920

        icon_right = detect_display_right_edge(screen_width)
        if icon_right is None:
            right_margin = POPUP_RIGHT_FALLBACK
        else:
            right_margin = screen_width - (icon_right + 6)
        right_margin = max(8, min(right_margin, screen_width - POPUP_WIDTH - 8))
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, right_margin)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.ever_inside = False
        self._closing = False
        self._loading = True
        self.outputs = {}
        self.output_names = []
        self.current_output = None
        self.selected_mode = None
        self.selected_scale = None

        self.connect("key-press-event", self.on_key)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("focus-out-event", self.on_focus_out)
        self.connect("button-press-event", self.on_bg_click)

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        self.server.bind(SOCKET_PATH)
        self.server.listen(1)
        self.server.setblocking(False)
        GLib.io_add_watch(self.server.fileno(), GLib.IO_IN, self.on_control)

        # 透明点击遮罩：覆盖状态栏以下的整个屏幕
        self.clickaway = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.clickaway.set_app_paintable(True)
        self.clickaway.set_decorated(False)
        rgba = Gdk.RGBA()
        rgba.parse("rgba(0,0,0,0)")
        self.clickaway.override_background_color(Gtk.StateFlags.NORMAL, rgba)
        self.clickaway.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
        )
        GtkLayerShell.init_for_window(self.clickaway)
        GtkLayerShell.set_layer(self.clickaway, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self.clickaway, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self.clickaway, GtkLayerShell.Edge.TOP, 0)
        for edge in (
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(self.clickaway, edge, True)
        self.clickaway.connect("button-press-event", lambda w, e: self.shutdown())
        self.clickaway.connect("motion-notify-event", self.on_clickaway_motion)

        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(12)
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="<b>显示设置</b>")
        title.set_use_markup(True)
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)
        refresh = Gtk.Button(label="刷新")
        refresh.connect("clicked", lambda b: self.refresh_data())
        header.pack_start(refresh, False, False, 0)
        close = Gtk.Button(label="✕")
        close.connect("clicked", lambda b: self.shutdown())
        header.pack_start(close, False, False, 0)
        root.pack_start(header, False, False, 0)

        # 用单选按钮切换显示器；下拉菜单会抢焦点导致窗口被误关
        self.output_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        root.pack_start(self.output_box, False, False, 0)

        self.info_label = Gtk.Label(label="")
        self.info_label.set_xalign(0)
        self.info_label.set_line_wrap(True)
        root.pack_start(self.info_label, False, False, 0)

        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                        False, False, 0)

        modes_title = Gtk.Label(label="<b>分辨率 / 刷新率</b>")
        modes_title.set_use_markup(True)
        modes_title.set_xalign(0)
        root.pack_start(modes_title, False, False, 0)

        self.modes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(210)
        scroll.add(self.modes_box)
        root.pack_start(scroll, True, True, 0)

        scale_title = Gtk.Label(label="<b>缩放倍率</b>")
        scale_title.set_use_markup(True)
        scale_title.set_xalign(0)
        root.pack_start(scale_title, False, False, 0)

        self.scale_grid = Gtk.Grid()
        self.scale_grid.set_column_spacing(6)
        self.scale_grid.set_row_spacing(4)
        root.pack_start(self.scale_grid, False, False, 0)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        self.status_label.set_line_wrap(True)
        root.pack_start(self.status_label, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        save = Gtk.Button(label="保存为默认")
        save.connect("clicked", self.on_save)
        buttons.pack_start(save, False, False, 0)
        buttons.pack_start(Gtk.Label(label=""), True, True, 0)
        footer = Gtk.Label(label="<small>设置仅本次会话生效；保存后写入 niri 配置</small>")
        footer.set_use_markup(True)
        buttons.pack_start(footer, False, False, 0)
        root.pack_start(buttons, False, False, 0)

    def _set_status(self, text):
        self.status_label.set_label(text)

    def refresh_data(self):
        # combo.set_active() 会同步触发 on_output_changed，避免重入刷新
        if getattr(self, "_refreshing", False):
            return False
        self._refreshing = True
        self._loading = True
        self.outputs = niri_outputs()
        if not self.outputs:
            self._set_status("无法获取显示器信息（niri 未运行？）")
            self._loading = False
            self._refreshing = False
            return False

        names = list(self.outputs.keys())
        previous = self.current_output
        self.output_names = names
        if previous in names:
            self.current_output = previous
        else:
            self.current_output = names[0]

        for child in self.output_box.get_children():
            self.output_box.remove(child)
        group = None
        for name in names:
            info = self.outputs[name]
            label = "%s · %s" % (name, info.get("model", ""))
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            if group is None:
                group = rb
            if name == self.current_output:
                rb.set_active(True)
            rb.connect("toggled", self.on_output_toggled, name)
            self.output_box.pack_start(rb, False, False, 0)
        self.output_box.show_all()

        self._update_info()
        self._rebuild_modes()
        self._rebuild_scales()
        self._loading = False
        self._refreshing = False
        return False

    def _update_info(self):
        info = self.outputs.get(self.current_output, {})
        idx = info.get("current_mode", 0)
        modes = info.get("modes", [])
        mode = modes[idx] if 0 <= idx < len(modes) else {}
        scale = info.get("logical", {}).get("scale", 1)
        physical = info.get("physical_size", [])
        text = "%s  %s %s\n当前：%s×%s @ %s Hz   缩放 %s" % (
            self.current_output,
            info.get("make", ""),
            info.get("model", ""),
            mode.get("width", "?"),
            mode.get("height", "?"),
            (mode.get("refresh_rate", 0) / 1000.0),
            scale,
        )
        if len(physical) == 2:
            text += "   物理尺寸 %s×%s mm" % (physical[0], physical[1])
        self.info_label.set_label(text)

    def _rebuild_modes(self):
        for child in self.modes_box.get_children():
            self.modes_box.remove(child)
        info = self.outputs.get(self.current_output, {})
        modes = info.get("modes", [])
        seen = set()
        keys = []
        for m in modes:
            key = (int(m["width"]), int(m["height"]), int(m["refresh_rate"]))
            if key not in seen:
                seen.add(key)
                keys.append(key)
        keys.sort(key=lambda k: (-k[0], -k[1], -k[2]))

        idx = info.get("current_mode", 0)
        cur = None
        if 0 <= idx < len(modes):
            m = modes[idx]
            cur = (int(m["width"]), int(m["height"]), int(m["refresh_rate"]))
        self.selected_mode = cur

        group = None
        last_res = None
        for w, h, rr in keys:
            if (w, h) != last_res:
                lbl = Gtk.Label(label="<b>%d × %d</b>" % (w, h))
                lbl.set_use_markup(True)
                lbl.set_xalign(0)
                self.modes_box.pack_start(lbl, False, False, 2)
                last_res = (w, h)
            text = "  %g Hz" % (rr / 1000.0)
            rb = Gtk.RadioButton.new_with_label_from_widget(group, text)
            if group is None:
                group = rb
            if cur == (w, h, rr):
                rb.set_active(True)
            rb.connect("toggled", self.on_mode_toggled, (w, h, rr))
            self.modes_box.pack_start(rb, False, False, 0)
        self.modes_box.show_all()

    def _rebuild_scales(self):
        for child in self.scale_grid.get_children():
            self.scale_grid.remove(child)
        info = self.outputs.get(self.current_output, {})
        current = float(info.get("logical", {}).get("scale", 1))
        choices = list(SCALE_CHOICES) + ["auto"]
        self.selected_scale = current if current in SCALE_CHOICES else "auto"

        group = None
        col = 0
        row = 0
        for value in choices:
            label = "自动" if value == "auto" else "%g" % value
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            if group is None:
                group = rb
            if value == self.selected_scale:
                rb.set_active(True)
            rb.connect("toggled", self.on_scale_toggled, value)
            self.scale_grid.attach(rb, col, row, 1, 1)
            col += 1
            if col >= 4:
                col = 0
                row += 1
        self.scale_grid.show_all()

    def on_output_toggled(self, button, name):
        if self._loading or not button.get_active():
            return
        self.current_output = name
        self.refresh_data()

    def on_mode_toggled(self, button, key):
        if self._loading or not button.get_active():
            return
        w, h, rr = key
        value = "%dx%d@%.3f" % (w, h, rr / 1000.0)
        self.selected_mode = key
        ok, msg = niri_output(self.current_output, ["mode", value])
        self._set_status(
            ("已应用：%s" % value) if ok else ("设置失败：%s" % msg)
        )
        GLib.timeout_add(700, self.refresh_data)

    def on_scale_toggled(self, button, value):
        if self._loading or not button.get_active():
            return
        self.selected_scale = value
        text = "auto" if value == "auto" else str(value)
        ok, msg = niri_output(self.current_output, ["scale", text])
        self._set_status(
            ("已应用缩放：%s" % text) if ok else ("设置失败：%s" % msg)
        )
        GLib.timeout_add(700, self.refresh_data)

    def on_refresh(self, button):
        self.refresh_data()

    def on_save(self, button):
        if self.selected_scale == "auto":
            self._set_status("保存默认前请先选择一个具体的缩放倍率")
            return
        if not self.selected_mode:
            self._set_status("无法获取当前分辨率")
            return
        w, h, rr = self.selected_mode
        mode_value = "%dx%d@%.3f" % (w, h, rr / 1000.0)
        scale_value = "%g" % self.selected_scale
        name = self.current_output

        if not os.path.exists(CONFIG_PATH):
            self._set_status("找不到 niri 配置文件：%s" % CONFIG_PATH)
            return
        backup = CONFIG_PATH + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(CONFIG_PATH, backup)
            with open(CONFIG_PATH) as f:
                lines = f.readlines()
        except OSError as e:
            self._set_status("备份/读取失败：%s" % e)
            return

        start = end = None
        for i, line in enumerate(lines):
            if start is None:
                if re.match(r'^\s*output\s+"%s"\s*\{' % re.escape(name), line):
                    start = i
                    depth = line.count("{") - line.count("}")
            else:
                depth += line.count("{") - line.count("}")
                if depth <= 0:
                    end = i
                    break
        if start is None or end is None:
            self._set_status("配置里没有 %s 的 output 段" % name)
            return

        body = []
        has_mode = has_scale = False
        for line in lines[start + 1:end]:
            stripped = line.strip()
            indent = line[:len(line) - len(line.lstrip())]
            if stripped.startswith("mode "):
                body.append('%smode "%s"\n' % (indent, mode_value))
                has_mode = True
            elif stripped.startswith("scale "):
                body.append("%sscale %s\n" % (indent, scale_value))
                has_scale = True
            else:
                body.append(line)
        extra = []
        if not has_mode:
            extra.append('    mode "%s"\n' % mode_value)
        if not has_scale:
            extra.append("    scale %s\n" % scale_value)
        lines[start + 1:end] = extra + body

        try:
            with open(CONFIG_PATH, "w") as f:
                f.writelines(lines)
        except OSError as e:
            self._set_status("写入配置失败：%s" % e)
            return
        self._set_status("已保存为默认：%s（备份 %s）" % (
            name, os.path.basename(backup)
        ))

    def on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.shutdown()
            return True
        return False

    def on_focus_out(self, widget, event):
        self.shutdown()
        return False

    def on_bg_click(self, widget, event):
        self.shutdown()
        return False

    def on_control(self, fd, condition):
        try:
            conn, _ = self.server.accept()
            data = conn.recv(64)
            conn.close()
        except OSError:
            return True
        if b"toggle" in data or b"close" in data:
            self.shutdown()
            return False
        return True

    def on_enter(self, widget, event):
        self.ever_inside = True
        return False

    def on_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        GLib.timeout_add(250, self._close_if_left)
        return False

    def _close_if_left(self):
        self.shutdown()
        return False

    def on_clickaway_motion(self, widget, event):
        if self.ever_inside:
            self.shutdown()
        return False

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        if getattr(self, "server", None) is not None:
            try:
                self.server.close()
            except OSError:
                pass
            self.server = None
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        if getattr(self, "clickaway", None):
            self.clickaway.destroy()
            self.clickaway = None
        self.destroy()
        Gtk.main_quit()


def send_toggle():
    for _ in range(10):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(SOCKET_PATH)
            s.sendall(b"toggle\n")
            s.close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


if __name__ == "__main__":
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        send_toggle()
        sys.exit(0)

    win = DisplayPopup()
    win.clickaway.show_all()
    win.show_all()
    Gtk.main()
