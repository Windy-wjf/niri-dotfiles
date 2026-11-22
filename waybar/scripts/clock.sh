#!/usr/bin/env sh
# 输出 JSON 给 waybar custom 模块：日期 + 星期，两行同一列
# 时间由独立的 clock 模块显示，形成两列布局
# 两行文字的居中对齐由 waybar 的 "justify": "center" 配置完成
printf '{"text":"%s&#10;%s"}\n' \
  "$(date '+%Y-%m-%d')" \
  "$(date '+%A')"
