#!/bin/zsh
set -e
domain="gui/$(id -u)"
label="local.node75.codex-status"
if launchctl print "$domain/$label" >/dev/null 2>&1; then
  launchctl bootout "$domain/$label"
fi
echo '已暂停键盘状态灯，退出时会恢复系统指示灯。下次登录会自动启动；可双击启动.command立即恢复。'
read '?按回车关闭窗口。'
