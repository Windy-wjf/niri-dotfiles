#!/usr/bin/env sh
# 独显（AMD Navi 44 / RX 9060 XT，PCI 03:00.0 -> card1）显存占用率
# 纯 shell，不使用 Python
u=$(cat /sys/class/drm/card1/device/mem_info_vram_used 2>/dev/null || echo 0)
t=$(cat /sys/class/drm/card1/device/mem_info_vram_total 2>/dev/null || echo 0)

if [ "$t" -gt 0 ] 2>/dev/null; then
    printf '%d%%\n' $(( (u * 100) / t ))
else
    printf -- '--\n'
fi
