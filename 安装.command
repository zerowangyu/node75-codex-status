#!/bin/zsh
set -e
cd -- "${0:A:h}"
python3 -B install.py install
read '?按回车关闭窗口。'
