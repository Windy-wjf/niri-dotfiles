#!/usr/bin/env python3
"""Waybar 网络悬浮窗：WiFi 列表、连接、断连、自动连接开关。
点击 waybar 的网络模块调用本脚本；按 ESC 或鼠标移出窗口自动关闭。
"""
import subprocess
import re
import os
import sys
import time
import socket
import fcntl
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

IFACE = "wlan0"
SOCKET_PATH = "/tmp/waybar-network-popup-%d.sock" % os.getuid()
LOCK_PATH = "/tmp/waybar-network-popup-%d.lock" % os.getuid()
BAR_HEIGHT = 32
POPUP_WIDTH = 360
POPUP_RIGHT_FALLBACK = 14


def run(args, timeout=8):
    try:
        return subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=timeout
        ).stdout.strip()
    except Exception:
        return ""


def nmcli(args):
    return run(["nmcli"] + args)


def unescape(s):
    return s.replace("\\:", ":").replace("\\\\", "\\")


def split_fields(line):
    return [unescape(x) for x in re.split(r"(?<!\\):", line)]


def signal_bars(level):
    try:
        n = int(level)
    except Exception:
        return "--"
    if n >= 80:
        return "▂▄▆█"
    if n >= 60:
        return "▂▄▆_"
    if n >= 40:
        return "▂▄__"
    if n >= 20:
        return "▂___"
    return "____"


def detect_network_right_edge(screen_width):
    """截取状态栏，找到网络模块（青色 #89dceb）的右边缘（逻辑像素）。

    网络模块紧挨在音量模块（黄色）左侧，利用这个相对位置定位，
    这样音量百分比、托盘图标数量变化时弹窗也能跟着网络图标移动。
    失败时返回 None，由调用方使用兜底边距。
    """
    try:
        from PIL import Image
    except Exception:
        return None

    tmp = "/tmp/waybar-network-bar.png"
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
    x_start = int(w * 0.65)  # 只看右侧，避开窗口标题等元素

    cyan_cols = []
    yellow_cols = []
    for x in range(x_start, w):
        has_cyan = has_yellow = False
        for y in range(h):
            r, g, b = pixels[x, y]
            if (not has_cyan and 100 <= r <= 175 and 190 <= g <= 245
                    and 210 <= b <= 255 and b > r + 50 and g > r + 40):
                has_cyan = True
            if (not has_yellow and 225 <= r <= 255 and 205 <= g <= 245
                    and 150 <= b <= 200):
                has_yellow = True
            if has_cyan and has_yellow:
                break
        if has_cyan:
            cyan_cols.append(x)
        if has_yellow:
            yellow_cols.append(x)

    if not cyan_cols or not yellow_cols:
        return None

    def to_runs(cols, gap=6):
        runs = []
        start = prev = cols[0]
        for x in cols[1:]:
            if x - prev > gap:
                runs.append((start, prev))
                start = x
            prev = x
        runs.append((start, prev))
        return runs

    cyan_runs = to_runs(cyan_cols)
    yellow_runs = to_runs(yellow_cols)
    first_yellow_left = yellow_runs[0][0]

    # 网络模块在音量模块左侧；取满足条件的青色区块中最靠右的一个
    candidates = [r for r in cyan_runs if r[1] < first_yellow_left + 12]
    if not candidates:
        candidates = cyan_runs
    return max(candidates, key=lambda r: r[1])[1]


class NetworkPopup(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.set_decorated(False)
        self.set_default_size(360, 460)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        # Wayland 层Shell：贴在状态栏下方，水平位置跟随网络图标
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        # niri 会把层Shell表面整体下移状态栏高度（exclusive zone），
        # 所以这里只需留 8px 间隙，实际显示位置就是状态栏下方 8px
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 8)

        display = Gdk.Display.get_default()
        monitor = None
        if display is not None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        screen_width = monitor.get_geometry().width if monitor else 1920

        net_right = detect_network_right_edge(screen_width)
        if net_right is None:
            right_margin = POPUP_RIGHT_FALLBACK
        else:
            right_margin = screen_width - (net_right + 6)
        # 保证弹窗不会超出屏幕左侧
        right_margin = max(8, min(right_margin, screen_width - POPUP_WIDTH - 8))
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, right_margin)
        # EXCLUSIVE 保证弹窗拿到键盘焦点，ESC 一定能收到
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.ever_inside = False
        self.dialog_open = False
        self._closing = False
        self.connect("key-press-event", self.on_key)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("focus-out-event", self.on_focus_out)
        # 点击弹窗内的空白/非按钮区域也关闭
        self.connect("button-press-event", self.on_bg_click)

        # 单实例控制：再次点击网络图标时通过 socket 通知本窗口关闭
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        self.server.bind(SOCKET_PATH)
        self.server.listen(1)
        self.server.setblocking(False)
        GLib.io_add_watch(self.server.fileno(), GLib.IO_IN, self.on_control)

        # 透明点击遮罩：覆盖状态栏以下的整个屏幕，点哪里都关闭
        # niri 会自动从状态栏下沿开始摆放层Shell表面，margin 设为 0 即可
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
        self.refresh()

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(12)
        self.add(root)

        # 标题栏
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="<b>WiFi 网络</b>")
        title.set_use_markup(True)
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)

        refresh = Gtk.Button(label="刷新")
        refresh.connect("clicked", lambda b: self.refresh())
        header.pack_start(refresh, False, False, 0)

        close = Gtk.Button(label="✕")
        close.connect("clicked", lambda b: self.shutdown())
        header.pack_start(close, False, False, 0)
        root.pack_start(header, False, False, 0)

        # 当前连接
        self.current = Gtk.Label(label="")
        self.current.set_xalign(0)
        self.current.set_line_wrap(True)
        root.pack_start(self.current, False, False, 0)

        self.disconnect_btn = Gtk.Button(label="断开当前 WiFi")
        self.disconnect_btn.connect("clicked", self.on_disconnect)
        root.pack_start(self.disconnect_btn, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(sep, False, False, 0)

        # 扫描结果列表
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(300)
        self.listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll.add(self.listbox)
        root.pack_start(scroll, True, True, 0)

    def current_ssid(self):
        for line in nmcli(
            ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"]
        ).splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == IFACE and parts[2] == "connected":
                return parts[3]
        return ""

    def saved_connections(self):
        out = nmcli(["-t", "-f", "NAME", "connection", "show"])
        return set(out.splitlines()) if out else set()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        cur = self.current_ssid()
        if cur:
            self.current.set_label("<b>已连接：</b>%s" % cur)
            self.current.set_use_markup(True)
            self.disconnect_btn.set_sensitive(True)
        else:
            self.current.set_label("<b>未连接 WiFi</b>")
            self.current.set_use_markup(True)
            self.disconnect_btn.set_sensitive(False)

        saved = self.saved_connections()
        rows = nmcli(
            ["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]
        ).splitlines()

        seen = set()
        for line in rows:
            parts = split_fields(line)
            if len(parts) < 2:
                continue
            ssid, signal = parts[0], parts[1]
            security = parts[2] if len(parts) > 2 else ""
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            self.listbox.pack_start(
                self._wifi_row(ssid, signal, security, ssid == cur, ssid in saved),
                False, False, 0,
            )

        if not seen:
            empty = Gtk.Label(label="附近没有发现 WiFi")
            empty.set_xalign(0)
            self.listbox.pack_start(empty, False, False, 0)

        self.show_all()

    def _wifi_row(self, ssid, signal, security, connected, saved):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        sig = Gtk.Label(label=signal_bars(signal))
        sig.set_width_chars(4)
        row.pack_start(sig, False, False, 0)

        name = Gtk.Label(label=ssid + ("  🔒" if security else ""))
        name.set_xalign(0)
        name.set_hexpand(True)
        name.set_ellipsize(3)
        row.pack_start(name, True, True, 0)

        auto = Gtk.CheckButton(label="自动")
        auto.set_active(False)
        if saved:
            info = nmcli(
                ["-t", "-f", "connection.autoconnect", "connection", "show", ssid]
            )
            auto.set_active("yes" in info)
        auto.connect("toggled", self.on_autoconnect, ssid)
        row.pack_start(auto, False, False, 0)

        if connected:
            btn = Gtk.Button(label="已连接")
            btn.set_sensitive(False)
        else:
            btn = Gtk.Button(label="连接")
            btn.connect("clicked", self.on_connect, ssid, security, saved)
        row.pack_start(btn, False, False, 0)

        return row

    def on_connect(self, button, ssid, security, saved):
        if saved:
            nmcli(["connection", "up", ssid])
        elif security:
            dialog = Gtk.Dialog(title="连接 %s" % ssid, parent=self, flags=0)
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                               Gtk.STOCK_OK, Gtk.ResponseType.OK)
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_placeholder_text("WiFi 密码")
            dialog.get_content_area().pack_start(entry, True, True, 8)
            dialog.show_all()
            self.dialog_open = True
            try:
                response = dialog.run()
            finally:
                self.dialog_open = False
            if response == Gtk.ResponseType.OK:
                password = entry.get_text()
                nmcli(["dev", "wifi", "connect", ssid, "password", password])
            dialog.destroy()
        else:
            nmcli(["dev", "wifi", "connect", ssid])
        GLib.timeout_add(800, self.refresh)

    def on_disconnect(self, button):
        nmcli(["dev", "disconnect", IFACE])
        GLib.timeout_add(800, self.refresh)

    def on_autoconnect(self, button, ssid):
        value = "yes" if button.get_active() else "no"
        nmcli(["connection", "modify", ssid, "connection.autoconnect", value])

    def on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.shutdown()
            return True
        return False

    def on_focus_out(self, widget, event):
        # 打开密码输入框时焦点会转给对话框，此时不要关闭主窗口
        if not self.dialog_open:
            self.shutdown()
        return False

    def on_bg_click(self, widget, event):
        # 按钮/勾选框会自己消费点击事件，能走到这里的都是空白区域
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
        # 在子控件之间移动时忽略，只有真正离开窗口才关闭
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        GLib.timeout_add(250, self._close_if_left)
        return False

    def _close_if_left(self):
        self.shutdown()
        return False

    def on_clickaway_motion(self, widget, event):
        # 只有鼠标曾经进入过弹窗、现在移出到遮罩，才关闭
        if self.ever_inside:
            self.shutdown()
        return False

    def shutdown(self):
        """关闭弹窗、遮罩、控制 socket 并退出主循环（可重复调用）"""
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
    """通知已经运行的弹窗关闭"""
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
    # 单实例锁：第二次点击时不再开新窗口，而是关掉已打开的窗口
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        send_toggle()
        sys.exit(0)

    win = NetworkPopup()
    win.clickaway.show_all()
    win.show_all()
    Gtk.main()
