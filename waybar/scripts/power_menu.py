#!/usr/bin/env python3
"""Waybar 电源菜单：锁屏 / 登出 / 关机 / 重启，合并成一个小窗口。
点击状态栏的电源图标打开；再点图标、点空白、ESC 或移出关闭。
"""
import os
import sys
import time
import socket
import fcntl
import subprocess
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

SOCKET_PATH = "/tmp/waybar-power-menu-%d.sock" % os.getuid()
LOCK_PATH = "/tmp/waybar-power-menu-%d.lock" % os.getuid()
BAR_HEIGHT = 32
POPUP_WIDTH = 240
POPUP_RIGHT_FALLBACK = 12


def spawn(cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception:
        pass


def detect_power_icon_center(screen_width):
    """截取状态栏，找到电源图标（红色 #f87171）的中心 x（逻辑像素）。

    扫描整条状态栏，让电源按钮不论在左/中/右都能被找到。
    """
    try:
        from PIL import Image
    except Exception:
        return None

    tmp = "/tmp/waybar-power-bar.png"
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
    for x in range(w):
        for y in range(h):
            r, g, b = pixels[x, y]
            # #f87171 = (248, 113, 113)，与粉色锁屏图标区分开
            if (r > 230 and 85 <= g <= 135 and 85 <= b <= 135
                    and r > g + 80 and r > b + 80):
                cols.append(x)
                break
    if not cols:
        return None
    return (cols[0] + cols[-1]) / 2.0


class PowerMenu(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.set_decorated(False)
        self.set_default_size(POPUP_WIDTH, 230)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        # niri 会把层Shell表面下移状态栏高度，所以这里只留 8px 间隙
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

        icon_center = detect_power_icon_center(screen_width)
        if icon_center is None:
            # 检测失败时回退到右上角
            right_margin = POPUP_RIGHT_FALLBACK
        else:
            # 窗口中心对齐电源图标中心；只锚定右侧（锚定左侧会被 layer shell 撑满宽度）。
            popup_center = icon_center
            right_margin = screen_width - (popup_center + POPUP_WIDTH / 2.0)
        right_margin = max(8, min(right_margin, screen_width - POPUP_WIDTH - 8))
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, int(right_margin))
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.ever_inside = False
        self._closing = False
        self.dialog_open = False

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
        for edge in (GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT,
                     GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.clickaway, edge, True)
        self.clickaway.connect("button-press-event", lambda w, e: self.shutdown())
        self.clickaway.connect("motion-notify-event", self.on_clickaway_motion)

        css = b"""
        button.power-lock { color: #f38ba8; }
        button.power-logout { color: #a6e3a1; }
        button.power-off { color: #f87171; }
        button.power-reboot { color: #89b4fa; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._build_ui()

    def _build_ui(self):
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.root.set_border_width(12)
        self.add(self.root)
        self._build_main_menu()

    def _clear_root(self):
        for child in self.root.get_children():
            self.root.remove(child)

    def _add_button(self, label, callback, style_class):
        btn = Gtk.Button(label=label)
        btn.set_size_request(-1, 38)
        btn.get_style_context().add_class(style_class)
        btn.connect("clicked", callback)
        self.root.pack_start(btn, False, False, 0)
        return btn

    def _build_main_menu(self):
        self._clear_root()
        title = Gtk.Label(label="<b>电源</b>")
        title.set_use_markup(True)
        title.set_xalign(0)
        self.root.pack_start(title, False, False, 0)
        self._add_button("🔒  锁屏", lambda b: self.act_lock(), "power-lock")
        self._add_button("  登出", lambda b: self.act_logout(), "power-logout")
        self._add_button("⏻  关机", lambda b: self.act_confirm("关机", ["systemctl", "poweroff"]), "power-off")
        self._add_button("⟳  重启", lambda b: self.act_confirm("重启", ["systemctl", "reboot"]), "power-reboot")
        self.root.show_all()

    def act_lock(self):
        spawn(["/home/wjf/.config/waybar/scripts/lock-and-blank.sh"])
        self.shutdown()

    def act_logout(self):
        spawn(["niri", "msg", "action", "quit"])
        self.shutdown()

    def act_confirm(self, name, cmd):
        # 独立 Gtk.MessageDialog 是普通窗口，会被 layer shell 的全屏遮罩盖住、
        # 且键盘被 EXCLUSIVE 模式锁住，按钮点不了。改为在 popup 内部内嵌确认。
        self.dialog_open = True
        self._clear_root()

        label = Gtk.Label(label="<b>确定要%s吗？</b>" % name)
        label.set_use_markup(True)
        label.set_xalign(0)
        self.root.pack_start(label, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel = Gtk.Button(label="取消")
        cancel.set_size_request(-1, 38)
        cancel.connect("clicked", lambda b: self._cancel_confirm())
        confirm = Gtk.Button(label="确定")
        confirm.set_size_request(-1, 38)
        confirm.get_style_context().add_class("power-off")
        confirm.connect("clicked", lambda b: self._do_confirm(cmd))
        box.pack_start(cancel, True, True, 0)
        box.pack_start(confirm, True, True, 0)
        self.root.pack_start(box, False, False, 0)
        self.root.show_all()

    def _cancel_confirm(self):
        self.dialog_open = False
        self._build_main_menu()

    def _do_confirm(self, cmd):
        spawn(cmd)
        self.shutdown()

    def on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.shutdown()
            return True
        return False

    def on_focus_out(self, widget, event):
        if not self.dialog_open:
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
        if event.detail == Gdk.NotifyType.INFERIOR or self.dialog_open:
            return False
        GLib.timeout_add(250, self._close_if_left)
        return False

    def _close_if_left(self):
        if not self.dialog_open:
            self.shutdown()
        return False

    def on_clickaway_motion(self, widget, event):
        if self.ever_inside and not self.dialog_open:
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

    win = PowerMenu()
    win.clickaway.show_all()
    win.show_all()
    Gtk.main()
