#!/usr/bin/env python3
"""Waybar 设置面板：切换状态栏模块 + 显示设置（分辨率/刷新率/缩放）。

点击 waybar 的设置齿轮调用本脚本；再次点击图标、点空白、ESC 或移出关闭。
- 「状态栏模块」页：勾选要显示的模块，应用后写回 config.jsonc 并重载 waybar。
- 「显示设置」页：复用 niri 的输出接口，调整模式/缩放并可保存为默认。
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

SOCKET_PATH = "/tmp/waybar-settings-popup-%d.sock" % os.getuid()
LOCK_PATH = "/tmp/waybar-settings-popup-%d.lock" % os.getuid()
WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config.jsonc")
NIRI_CONFIG = os.environ.get(
    "NIRI_CONFIG", os.path.expanduser("~/.config/niri/config.kdl")
)
POPUP_WIDTH = 460
POPUP_RIGHT_MARGIN = 8
SETTINGS_MODULE = "custom/settings"

MODULE_LABELS = {
    "niri/workspaces": "工作区",
    "niri/window": "窗口标题",
    "cpu": "CPU 占用",
    "memory": "内存占用",
    "custom/vram": "显存占用",
    "custom/lock": "锁屏按钮",
    "network": "网络",
    "pulseaudio": "音量",
    "custom/brightness": "亮度",
    "custom/notification": "通知按钮",
    "custom/power": "电源菜单按钮",
    "custom/settings": "设置按钮（始终保留）",
    "tray": "系统托盘",
    "custom/clock": "日期",
    "clock": "时间",
}

# 没在配置里出现过的模块，重新启用时放到哪个区域。
DEFAULT_ZONE = {
    "niri/workspaces": "modules-left",
    "niri/window": "modules-center",
}
ALL_MODULES = list(MODULE_LABELS.keys())

MODULE_KEYS = ("modules-left", "modules-center", "modules-right")
MODULE_RE = re.compile(
    r'^(\s*)"(modules-left|modules-center|modules-right)"\s*:\s*\[([^\]]*)\]'
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


def new_checkbox(text, active=False):
    """方框内打对钩的复选框，用 Nerd Font 字形，不依赖主题或图标主题。

    U+F14A = 方框对钩，U+F046 = 空方框（CaskaydiaCove Nerd Font 均包含）。
    """
    cb = Gtk.CheckButton()
    cb.set_property("draw-indicator", False)

    def sync(button):
        mark = "\uf14a" if button.get_active() else "\uf046"
        button.set_label(mark + "  " + text)

    cb.connect("toggled", sync)
    cb.set_active(active)
    sync(cb)
    return cb


# --------------------------------------------------------------------------
# 模块开关：解析 / 写回 waybar config.jsonc
# --------------------------------------------------------------------------
def parse_modules():
    with open(WAYBAR_CONFIG) as f:
        lines = f.readlines()
    info = {}
    for index, line in enumerate(lines):
        m = MODULE_RE.match(line)
        if not m:
            continue
        indent, key, body = m.group(1), m.group(2), m.group(3)
        mods = [x.strip().strip('"\'') for x in body.split(",") if x.strip()]
        info[key] = (index, indent, mods)
    return lines, info


def save_modules(enabled, order=None):
    """enabled: set，要显示的模块；order: 拖动排序后的模块顺序（可选）。"""
    try:
        lines, info = parse_modules()
        if not info:
            return False, "未找到模块列表配置"
        backup = WAYBAR_CONFIG + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(WAYBAR_CONFIG, backup)

        # 记录每个模块当前所在区域；新启用的模块用默认区域。
        zone_of = {}
        for key in MODULE_KEYS:
            if key in info:
                for m in info[key][2]:
                    zone_of[m] = key
        for m in enabled:
            if m not in zone_of:
                zone_of[m] = DEFAULT_ZONE.get(m, "modules-right")

        # 按拖动后的顺序排列（同一区域内的相对顺序由 order 决定）。
        sequence = None
        if order:
            sequence = [m for m in order if m in enabled]
            sequence += [m for m in enabled if m not in sequence]

        changed = False
        for key in MODULE_KEYS:
            if key not in info:
                continue
            index, indent, mods = info[key]
            if sequence is not None:
                kept = [
                    m for m in sequence
                    if m != SETTINGS_MODULE and zone_of.get(m) == key
                ]
            else:
                kept = []
                for m in mods:
                    if m == SETTINGS_MODULE:
                        continue  # 设置按钮统一放到最后
                    if m in enabled:
                        kept.append(m)
                # 把新勾选、原本不在此数组的模块加回来。
                for m in enabled:
                    if m == SETTINGS_MODULE:
                        continue
                    if zone_of.get(m) == key and m not in mods:
                        kept.append(m)
            if key == "modules-right":
                kept.append(SETTINGS_MODULE)
            if kept != mods:
                changed = True
            # 保留原行末尾的逗号，避免破坏 JSONC 语法。
            trailing = (
                "," if lines[index].rstrip("\n").rstrip().endswith(",") else ""
            )
            new_line = '%s"%s": [%s]%s\n' % (
                indent, key, ", ".join('"%s"' % m for m in kept), trailing
            )
            lines[index] = new_line
        if not changed:
            return True, "没有变化"
        with open(WAYBAR_CONFIG, "w") as f:
            f.writelines(lines)
    except OSError as e:
        return False, "读写配置失败：%s" % e

    ok, msg = run(["pkill", "-USR2", "waybar"])
    note = "，已重载 waybar" if ok else "，请手动重启 waybar"
    return True, "已保存（备份 %s）%s" % (os.path.basename(backup), note)


# --------------------------------------------------------------------------
# 显示设置：niri 输出接口
# --------------------------------------------------------------------------
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


class ModulesPage(Gtk.Box):
    def __init__(self):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_border_width(10)
        self.toggles = {}
        self._drag_module = None

        intro = Gtk.Label(
            label=("<small>勾选显示/隐藏；拖动左侧 <b>☰</b> 把手调整顺序"
                   "（保持原区域）；点击「应用」后生效。</small>")
        )
        intro.set_use_markup(True)
        intro.set_xalign(0)
        self.pack_start(intro, False, False, 0)

        _, info = parse_modules()
        present = []
        for key in MODULE_KEYS:
            if key in info:
                for m in info[key][2]:
                    if m not in present:
                        present.append(m)

        # 列出所有支持的模块（包括当前未显示的），用勾选状态表示是否显示。
        candidates = list(ALL_MODULES)
        for m in present:
            if m not in candidates:
                candidates.append(m)

        # 初始顺序：按配置里的顺序，再补上未显示的模块。
        ordered = []
        for key in MODULE_KEYS:
            if key in info:
                for m in info[key][2]:
                    if m not in ordered:
                        ordered.append(m)
        for m in candidates:
            if m not in ordered:
                ordered.append(m)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(300)

        targets = [Gtk.TargetEntry.new("text/plain", 0, 0)]
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.DROP,
            targets, Gdk.DragAction.MOVE,
        )
        self.listbox.connect("drag-motion", self.on_drag_motion)
        self.listbox.connect("drag-leave", self.on_drag_leave)
        self.listbox.connect("drag-drop", self.on_drag_drop)

        for m in ordered:
            row = Gtk.ListBoxRow()
            row.module_id = m
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            hbox.set_border_width(2)

            handle = Gtk.Label(label="\uf0c9")  # fa-bars
            handle.set_tooltip_text("拖动调整顺序")
            handle.set_xalign(0)
            handle.drag_source_set(
                Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.MOVE
            )
            handle.connect("drag-begin", self.on_drag_begin, m)
            handle.connect("drag-end", self.on_drag_end)
            hbox.pack_start(handle, False, False, 0)

            cb = new_checkbox(MODULE_LABELS.get(m, m), m in present)
            if m == SETTINGS_MODULE:
                cb.set_active(True)
                cb.set_sensitive(False)
                cb.set_tooltip_text("设置按钮不能隐藏，否则无法再次打开本面板")
            hbox.pack_start(cb, False, False, 0)

            place = key_of(info, m) if m in present else "未显示"
            loc = Gtk.Label(label="<small>%s</small>" % place)
            loc.set_use_markup(True)
            loc.set_xalign(0)
            hbox.pack_end(loc, False, False, 0)

            row.add(hbox)
            self.listbox.add(row)
            self.toggles[m] = cb

        scroll.add(self.listbox)
        self.pack_start(scroll, True, True, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        apply = Gtk.Button(label="应用")
        apply.connect("clicked", self.on_apply)
        btns.pack_start(apply, False, False, 0)
        all_on = Gtk.Button(label="全部显示")
        all_on.connect("clicked", lambda b: self.set_all(True))
        btns.pack_start(all_on, False, False, 0)
        self.pack_start(btns, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)

    def set_all(self, active):
        for m, cb in self.toggles.items():
            if cb.get_sensitive():
                cb.set_active(active)

    def current_order(self):
        order = []
        index = 0
        while True:
            row = self.listbox.get_row_at_index(index)
            if row is None:
                break
            order.append(row.module_id)
            index += 1
        return order

    def _row_of(self, module_id):
        index = 0
        while True:
            row = self.listbox.get_row_at_index(index)
            if row is None:
                return None
            if getattr(row, "module_id", None) == module_id:
                return row
            index += 1

    def on_drag_begin(self, widget, context, module_id):
        self._drag_module = module_id
        self.get_toplevel()._dragging = True

    def on_drag_end(self, widget, context):
        self._drag_module = None
        self.listbox.drag_unhighlight_row()
        self.get_toplevel()._dragging = False

    def on_drag_motion(self, widget, context, x, y, time):
        row = self.listbox.get_row_at_y(y)
        self.listbox.drag_unhighlight_row()
        if row is not None:
            self.listbox.drag_highlight_row(row)
            context.drag_status(Gdk.DragAction.MOVE, time)
            return True
        return False

    def on_drag_leave(self, widget, context, time):
        self.listbox.drag_unhighlight_row()
        return False

    def on_drag_drop(self, widget, context, x, y, time):
        target = self.listbox.get_row_at_y(y)
        source_id = self._drag_module
        if target is None or not source_id:
            return False
        source = self._row_of(source_id)
        if source is None:
            return False
        src = source.get_index()
        dst = target.get_index()
        if src != dst:
            self.listbox.remove(source)
            if src < dst:
                dst -= 1
            self.listbox.insert(source, dst)
        return True

    def on_apply(self, button):
        enabled = {
            m for m, cb in self.toggles.items()
            if cb.get_sensitive() and cb.get_active()
        }
        ok, msg = save_modules(enabled, self.current_order())
        self.status.set_label(("✔ " if ok else "✘ ") + msg)


def key_of(info, module):
    for key in MODULE_KEYS:
        if key in info and module in info[key][2]:
            return {"modules-left": "左侧", "modules-center": "中间",
                    "modules-right": "右侧"}[key]
    return ""


class DisplayPage(Gtk.Box):
    def __init__(self):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_border_width(10)
        self._loading = True
        self.outputs = {}
        self.output_names = []
        self.current_output = None
        self.selected_mode = None
        self.selected_scale = None
        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        self.output_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(self.output_box, False, False, 0)

        self.info_label = Gtk.Label(label="")
        self.info_label.set_xalign(0)
        self.info_label.set_line_wrap(True)
        self.pack_start(self.info_label, False, False, 0)

        self.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )

        title = Gtk.Label(label="<b>分辨率 / 刷新率</b>")
        title.set_use_markup(True)
        title.set_xalign(0)
        self.pack_start(title, False, False, 0)

        self.modes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.add(self.modes_box)
        self.pack_start(scroll, True, True, 0)

        scale_title = Gtk.Label(label="<b>缩放倍率</b>")
        scale_title.set_use_markup(True)
        scale_title.set_xalign(0)
        self.pack_start(scale_title, False, False, 0)

        self.scale_grid = Gtk.Grid()
        self.scale_grid.set_column_spacing(6)
        self.scale_grid.set_row_spacing(4)
        self.pack_start(self.scale_grid, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        save = Gtk.Button(label="保存为默认")
        save.connect("clicked", self.on_save)
        btns.pack_start(save, False, False, 0)
        self.pack_start(btns, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)

        footer = Gtk.Label(
            label="<small>即时生效；保存后写入 niri 配置（会先备份）</small>"
        )
        footer.set_use_markup(True)
        self.pack_start(footer, False, False, 0)

    def refresh_data(self):
        if getattr(self, "_refreshing", False):
            return False
        self._refreshing = True
        self._loading = True
        self.outputs = niri_outputs()
        if not self.outputs:
            self.status.set_label("无法获取显示器信息（niri 未运行？）")
            self._loading = False
            self._refreshing = False
            return False
        names = list(self.outputs.keys())
        previous = self.current_output
        self.output_names = names
        self.current_output = previous if previous in names else names[0]

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
        text = "%s  %s %s\n当前：%s×%s @ %g Hz   缩放 %s" % (
            self.current_output,
            info.get("make", ""),
            info.get("model", ""),
            mode.get("width", "?"),
            mode.get("height", "?"),
            (mode.get("refresh_rate", 0) / 1000.0),
            scale,
        )
        self.info_label.set_label(text)

    def _rebuild_modes(self):
        for child in self.modes_box.get_children():
            self.modes_box.remove(child)
        info = self.outputs.get(self.current_output, {})
        modes = info.get("modes", [])
        seen, keys = set(), []
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

        group, last_res = None, None
        for w, h, rr in keys:
            if (w, h) != last_res:
                lbl = Gtk.Label(label="<b>%d × %d</b>" % (w, h))
                lbl.set_use_markup(True)
                lbl.set_xalign(0)
                self.modes_box.pack_start(lbl, False, False, 2)
                last_res = (w, h)
            rb = Gtk.RadioButton.new_with_label_from_widget(group, "  %g Hz" % (rr / 1000.0))
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

        group, col, row = None, 0, 0
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
                col, row = 0, row + 1
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
        self.status.set_label(("已应用：" if ok else "设置失败：") + (value if ok else msg))

    def on_scale_toggled(self, button, value):
        if self._loading or not button.get_active():
            return
        self.selected_scale = value
        text = "auto" if value == "auto" else str(value)
        ok, msg = niri_output(self.current_output, ["scale", text])
        self.status.set_label(("已应用缩放：" if ok else "设置失败：") + (text if ok else msg))

    def on_save(self, button):
        if self.selected_scale == "auto":
            self.status.set_label("保存默认前请先选择一个具体的缩放倍率")
            return
        if not self.selected_mode:
            self.status.set_label("无法获取当前分辨率")
            return
        w, h, rr = self.selected_mode
        mode_value = "%dx%d@%.3f" % (w, h, rr / 1000.0)
        scale_value = "%g" % self.selected_scale
        name = self.current_output

        if not os.path.exists(NIRI_CONFIG):
            self.status.set_label("找不到 niri 配置：%s" % NIRI_CONFIG)
            return
        backup = NIRI_CONFIG + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(NIRI_CONFIG, backup)
            with open(NIRI_CONFIG) as f:
                lines = f.readlines()
        except OSError as e:
            self.status.set_label("备份/读取失败：%s" % e)
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
            self.status.set_label("配置里没有 %s 的 output 段" % name)
            return

        body, has_mode, has_scale = [], False, False
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
            with open(NIRI_CONFIG, "w") as f:
                f.writelines(lines)
        except OSError as e:
            self.status.set_label("写入配置失败：%s" % e)
            return
        self.status.set_label("已保存为默认：%s（备份 %s）" % (
            name, os.path.basename(backup)
        ))


class SettingsPopup(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.set_decorated(False)
        self.set_default_size(POPUP_WIDTH, 620)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 8)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, POPUP_RIGHT_MARGIN)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.ever_inside = False
        self._closing = False
        self.connect("key-press-event", self.on_key)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)
        # 不连接 button-press-event：子控件的点击会冒泡到顶层，
        # 否则点复选框/标签页就会把面板关掉。空白点击由 clickaway 遮罩处理。

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
        for edge in (
            GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(self.clickaway, edge, True)
        self.clickaway.connect("button-press-event", lambda w, e: self.shutdown())
        self.clickaway.connect("motion-notify-event", self.on_clickaway_motion)

        notebook = Gtk.Notebook()
        notebook.append_page(ModulesPage(), Gtk.Label(label="状态栏模块"))
        notebook.append_page(DisplayPage(), Gtk.Label(label="显示设置"))
        self.add(notebook)

    def on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.shutdown()
            return True
        return False

    def on_enter(self, widget, event):
        self.ever_inside = True
        return False

    def on_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        GLib.timeout_add(250, self._close_if_left)
        return False

    def _close_if_left(self):
        if getattr(self, "_dragging", False):
            return False
        self.shutdown()
        return False

    def on_clickaway_motion(self, widget, event):
        if self.ever_inside and not getattr(self, "_dragging", False):
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

    win = SettingsPopup()
    win.clickaway.show_all()
    win.show_all()
    Gtk.main()
