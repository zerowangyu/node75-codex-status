#!/bin/zsh
set -e
domain="gui/$(id -u)"
label="local.node75.codex-status"
plist="$HOME/Library/LaunchAgents/$label.plist"
if [[ ! -f "$plist" ]]; then
  echo '请先运行安装.command。'
elif launchctl print "$domain/$label" >/dev/null 2>&1; then
  echo '键盘状态灯已经运行。'
else
  launchctl bootstrap "$domain" "$plist"
  echo '已启动键盘状态灯，下一次Codex事件会触发联动。'
fi
read '?按回车关闭窗口。'
