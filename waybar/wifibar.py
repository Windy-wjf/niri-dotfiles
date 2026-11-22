#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wifibar — waybar 的 WiFi 模块 + niri 悬浮菜单
  模式1（默认，常驻）: 轮询 nmcli，状态变化时把 JSON 写到 stdout；
                       从 stdin 读 waybar 的点击/滚动 IPC，管理菜单开关。
  模式2（--menu）: pywayland 直连 zwlr_layer_shell_v1，cairo 绘制悬浮菜单。
依赖: python3-cairo, pywayland
"""
import os
import sys
import json
import time
import select
import ctypes
import fcntl
import signal
import subprocess
import threading

SCRIPT = os.path.abspath(__file__)
MENU_PIDFILE = "/tmp/wifibar-menu.pid"
WIFI_ICON = "\U0016A0E8"
ESC_KEYSYM = 9


# ---------------- nmcli 封装 ----------------

def sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def sh_ok(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def wifi_state():
    """返回 dict: conn/ssid/dev/sig/auto（未连接时 ssid=None）"""
    st = {"conn": False, "ssid": None, "dev": None, "sig": None, "auto": None}
    for line in sh("nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev show")
            .splitlines():
        p = line.split(":")
        if len(p) >= 4 and p[1] == "wifi" and p[2] == "connected":
            st["conn"] = True
            st["dev"] = p[0]
            st["ssid"] = p[3] or None
            st["auto"] = sh(
                "nmcli -g AUTOCONNECT.CONNECTION nmcli -c never "
                "con show 2>/dev/null") != ""  # 占位，下面直接读 con
    if st["ssid"]:
        out = sh("nmcli -t -f AUTOCONNECT con show %r" % st["ssid"])
        st["auto"] = out.strip() == "yes"
    if st["conn"]:
        for line in sh("nmcli -t -f DEVICE,SIGNAL,IN-USE,SSID dev wifi list")
                .splitlines():
            p = line.split(":")
            if len(p) >= 3 and p[2] == "yes" and p[0] == st["dev"]:
                try:
                    st["sig"] = int(p[1])
                except ValueError:
                    pass
                break
    return st


def wifi_nets(limit=8):
    """返回 [(ssid, signal, has_key, in_use), ...] 按信号排序"""
    nets = []
    for line in sh("nmcli -t -f SSID,SIGNAL,SECURITY,IN-USE dev wifi list")
            .splitlines():
        p = line.split(":")
        if len(p) >= 2 and p[0]:
            try:
                sig = int(p[1])
            except ValueError:
                sig = 0
            has_key = len(p) > 2 and p[2] != ""
            in_use = len(p) > 3 and p[3] == "yes"
            nets.append((p[0], sig, has_key, in_use))
    nets.sort(key=lambda n: -n[1])
    return nets[:limit]


def set_autos(on):
    st = wifi_state()
    if st["ssid"]:
        sh_ok("nmcli con modify %r connection.autoconnect %s"
              % (st["ssid"], "yes" if on else "no"))


# ---------------- 模式1: waybar 常驻模块 ----------------

def menu_running():
    try:
        with open(MENU_PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


def menu_start():
    try:
        log = open("/tmp/wifibar-menu.log", "a")
    except Exception:
        log = None
    p = subprocess.Popen(
        [sys.executable, SCRIPT, "--menu"],
        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        start_new_session=True)
    with open(MENU_PIDFILE, "w") as f:
        f.write(str(p.pid))
    return p


def menu_stop():
    pid = menu_running()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    try:
        os.unlink(MENU_PIDFILE)
    except Exception:
        pass


def module_main():
    last_text = None

    def emit():
        nonlocal last_text
        st = wifi_state()
        if st["conn"]:
            sig = st["sig"] if st["sig"] is not None else 0
            text = "%s %s (%d%%)" % (WIFI_ICON, st["ssid"], sig)
            tip = ("信号 %d%%\n自动连接: %s\n点击: 打开菜单\n"
                   "滚轮上/下: 自动连接 开/关") % (
                       sig, "开" if st["auto"] else "关")
        else:
            text = WIFI_ICON + " 未连接"
            tip = "点击: 打开菜单（可扫描并连接网络）"
        if text != last_text:
            last_text = text
            print(json.dumps({"text": text, "tooltip": tip},
                             ensure_ascii=False), flush=True)

    def poll_loop():
        while True:
            try:
                emit()
            except Exception:
                pass
            time.sleep(2.0)

    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
    emit()

    fd = sys.stdin.fileno()
    try:
        fcntl.ioctl(fd, 0x5401,
                    struct.pack("i", 0))  # 非阻塞? 用 select 更稳，忽略错误
    except Exception:
        pass
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 1.0)
        if not r:
            continue
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:
            continue
        ev = msg.get("event")
        if ev == "click" and msg.get("button") == 1:
            if menu_running():
                menu_stop()
            else:
                menu_start()
        elif ev == "scroll":
            dy = msg.get("deltaY", 0)
            if dy > 0:
                set_autos(True)
            elif dy < 0:
                set_autos(False)
            emit()
    try:
        menu_stop()
    except Exception:
        pass


# ---------------- 模式2: 悬浮菜单 ----------------

def menu_main():
    from pywayland.client.display import Display
    import cairo
    import mmap as _mm

    display = Display()
    display.connect()
    registry = display.get_registry()

    compositor = None
    shm = None
    layer_shell = None
    wl_output = None
    seat = None
    scale = [1]
    running = {"v": True}

    def on_global(proxy, name, gid, ver):
        nonlocal compositor, shm, layer_shell, wl_output, seat
        if name == "wl_compositor":
            compositor = registry.bind(name, ver, proxy)
        elif name == "wl_shm":
            shm = registry.bind(name, ver, proxy)
        elif name == "zwlr_layer_shell_v1":
            layer_shell = registry.bind(name, ver, proxy)
        elif name == "wl_output":
            wl_output = registry.bind(name, ver, proxy)
        elif name == "wl_seat":
            seat = registry.bind(name, ver, proxy)

    registry.dispatcher["global"] = on_global
    display.roundtrip()
    if not (compositor and shm and layer_shell and seat):
        print("缺少所需 Wayland 全局: compositor=%s shm=%s layer=%s seat=%s"
              % (compositor, shm, layer_shell, seat), file=sys.stderr)
        display.destroy()
        return 1

    if wl_output:
        def on_out_scale(p, factor):
            scale[0] = factor
        wl_output.dispatcher["scale"] = on_out_scale
        display.roundtrip()

    surface = compositor.create_surface()
    ls = layer_shell.get_layer_surface(surface, 2, "right", "top")  # top 层
    # niri 的 layer-shell: anchor 通过 wl_surface 的 layer 属性实现
    # 用最小尺寸，实际由 cairo 绘制；位置靠 niri 的 layer-shell 配置
    from pywayland.protocol.wl_shm import WlShmFormat
    state = {"conn": False, "ssid": None, "dev": None, "sig": None,
             "auto": True, "nets": [], "hover": -1, "msg": None,
             "msg_until": 0}
    dirty = [True]
    W = 340.0

    def H():
        return 40.0 + 14.0 * max(1, len(state["nets"])) + (30.0 if state["nets"] else 0)

    def refresh():
        st = wifi_state()
        state["conn"], state["ssid"], state["dev"] = st["conn"], st["ssid"], st["dev"]
        state["sig"], state["auto"] = st["sig"], (st["auto"] if st["auto"] is not None else True)
        state["nets"] = wifi_nets()
        dirty[0] = True

    def close_menu():
        running["v"] = False

    def do_action(i):
        r = state["rows"]
        if i < 0 or i >= len(r):
            return
        kind, payload = r[i]
        if kind == "disconnect":
            if state["dev"]:
                sh_ok("nmcli dev disconnect %r" % state["dev"])
            close_menu()
        elif kind == "auto":
            if state["ssid"]:
                want = "no" if state["auto"] else "yes"
                sh_ok("nmcli con modify %r connection.autoconnect %s"
                      % (state["ssid"], want))
                state["auto"] = not state["auto"]
                dirty[0] = True
        elif kind == "net":
            ok = sh_ok("nmcli dev wifi connect %r" % payload[0], timeout=20)
            if ok:
                close_menu()
            else:
                state["msg"] = "连接失败（需要密码？）"
                state["msg_until"] = time.time() + 4
                dirty[0] = True

    # ---- 指针/键盘 ----
    pointer = None

    def on_caps(p, caps):
        nonlocal pointer
        if pointer is None and (caps & 1):
            pointer = seat.get_pointer()
            pointer.dispatcher["enter"] = lambda p, s, sx, sy: None
            pointer.dispatcher["leave"] = lambda p, s: (state.__setitem__("hover", -1), __import__("builtins").__setattr__(dirty, 0, True) and None)
            pointer.dispatcher["motion"] = on_motion
            pointer.dispatcher["button"] = on_button

    def on_motion(p, t_, xh, yh):
        h = row_at(yh / 65536.0)
        if h != state["hover"]:
            state["hover"] = h
            dirty[0] = True

    def on_button(p, s, t_, b, st, s2):
        if b == 1 and st == 1:
            do_action(state["hover"])
        display.roundtrip()

    seat.dispatcher["capabilities"] = on_caps
    display.roundtrip()
    kb = seat.get_keyboard()
    kb.dispatcher["key"] = lambda p, s, t_, keysym, st, rep: close_menu() if (st == 1 and keysym == ESC_KEYSYM) else None

    # ---- 布局 ----
    def rows():
        r = []
        if state["conn"]:
            r.append(("disconnect", None))
            r.append(("auto", None))
        if state["nets"]:
            r.append(("sep", None))
            r.extend(("net", n) for n in state["nets"])
        return r

    state["rows"] = rows()

    def row_y(i):
        y = 40.0
        for j in range(i):
            y += 14.0 if state["rows"][j][0] != "sep" else 10.0
        return y

    def row_at(y):
        y0 = 40.0
        for i, (kind, _) in enumerate(state["rows"]):
            h = 10.0 if kind == "sep" else 14.0
            if kind != "sep" and y0 <= y < y0 + h:
                return i
            y0 += h
        return -1

    def total_h():
        y = 40.0
        for kind, _ in state["rows"]:
            y += 10.0 if kind == "sep" else 14.0
        if state["msg"] and time.time() < state["msg_until"]:
            y += 18.0
        return y

    # ---- 绘制 ----
    sfd = ctypes.CDLL(None, use_errno=True).memfd_create(b"wifibar", 0)

    def rrect(cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def draw(cr):
        import math
        th = total_h()
        cr.set_source_rgb(0.094, 0.102, 0.141)  # #181825
        rrect(cr, 0, 0, W, th, 10)
        cr.fill()
        cr.set_source_rgb(0.4, 0.42, 0.48)
        cr.set_line_width(1)
        rrect(cr, 0.5, 0.5, W - 1, th - 1, 10)
        cr.stroke()
        # 标题
        cr.select_font_face("Noto Sans CJK SC", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(14)
        cr.set_source_rgb(0.80, 0.84, 0.96)
        cr.move_to(14, 26)
        cr.show_text("Wi-Fi")
        cr.select_font_face("Noto Sans CJK SC", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12)
        cr.set_source_rgb(0.54, 0.82, 0.72) if state["conn"] else cr.set_source_rgb(0.56, 0.58, 0.64)
        cr.move_to(W - 76, 26)
        cr.show_text("已连接" if state["conn"] else "未连接")
        for i, (kind, payload) in enumerate(state["rows"]):
            y0 = row_y(i)
            if kind == "sep":
                cr.set_source_rgb(0.30, 0.32, 0.38)
                cr.rectangle(14, y0 + 4.5, W - 28, 1)
                cr.fill()
                continue
            if i == state["hover"]:
                cr.set_source_rgb(0.16, 0.17, 0.23)
                rrect(cr, 8, y0 + 1, W - 16, 12, 5)
                cr.fill()
            yb = y0 + 7
            if kind == "disconnect":
                cr.set_source_rgb(0.86, 0.46, 0.48)
                cr.set_font_size(12)
                cr.move_to(20, yb + 4)
                cr.show_text("断  开")
            elif kind == "auto":
                cr.set_source_rgb(0.54, 0.86, 0.93) if state["auto"] else cr.set_source_rgb(0.56, 0.58, 0.64)
                cr.set_font_size(12)
                cr.move_to(20, yb + 4)
                cr.show_text("自动连接: " + ("开" if state["auto"] else "关"))
            elif kind == "net":
                ssid, sig, has_key, in_use = payload
                bars = min(4, 1 + sig // 25)
                for b in range(4):
                    hgt = 4.5 + b * 3.0
                    cr.set_source_rgb(0.54, 0.86, 0.93) if b < bars else cr.set_source_rgb(0.30, 0.32, 0.38)
                    cr.rectangle(20 + b * 5.5, yb + 8.5 - hgt, 3.5, hgt)
                    cr.fill()
                cr.set_source_rgb(0.80, 0.84, 0.96) if in_use else cr.set_source_rgb(0.62, 0.64, 0.70)
                cr.set_font_size(12)
                label = ssid if len(ssid) <= 26 else ssid[:25] + "…"
                cr.move_to(48, yb + 4)
                cr.show_text(label)
                if has_key:
                    cr.set_source_rgb(0.56, 0.58, 0.64)
                    cr.set_line_width(1.2)
                    cr.rectangle(W - 78, yb - 1.5, 9, 7)
                    cr.fill()
                    cr.new_sub_path()
                    cr.arc(W - 73.5, yb - 1.5, 4, math.pi, 2 * math.pi)
                    cr.stroke()
                if in_use:
                    cr.set_source_rgb(0.54, 0.86, 0.93)
                    cr.set_font_size(13)
                    cr.move_to(W - 56, yb + 4)
                    cr.show_text("✓")
        if state["msg"] and time.time() < state["msg_until"]:
            cr.set_source_rgb(0.86, 0.46, 0.48)
            cr.set_font_size(11)
            cr.move_to(14, total_h() - 8)
            cr.show_text(state["msg"])

    def commit_frame():
        s = scale[0]
        bw, bh = int(W * s), int(total_h() * s)
        stride = bw * 4
        size = stride * bh
        os.ftruncate(sfd, size)
        mm = _mm.mmap(-1, size)
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, bw, bh))
        cr.scale(s, s)
        draw(cr)
        if not hasattr(commit_frame, "pool"):
            commit_frame.pool = shm.create_pool(sfd, size)
        buf = commit_frame.pool.create_buffer(0, bw, bh, stride, 0)
        surface.attach(buf)
        surface.damage(0, 0, int(W), int(total_h()))
        surface.commit()
        mm.flush()
        mm.close()

    ls.set_layer(2)  # top
    surface.frame  # noop
    running_flag = running

    # 后台 2s 刷新
    def poller():
        while running["v"]:
            time.sleep(2.0)
            try:
                refresh()
            except Exception:
                pass

    threading.Thread(target=poller, daemon=True).start()
    refresh()

    fd = display.get_fd()
    try:
        while running["v"]:
            r, _, _ = select.select([fd], [], [], 0.03)
            if r:
                display.read()
            display.dispatch(block=False)
            if dirty[0]:
                try:
                    commit_frame()
                except Exception as e:
                    print("frame:", e, file=sys.stderr)
                dirty[0] = False
            state["rows"] = rows()
    finally:
        try:
            display.destroy()
        except Exception:
            pass
    return 0


def main():
    if "--menu" in sys.argv:
        sys.exit(menu_main() or 0)
    else:
        module_main()


if __name__ == "__main__":
    main()
