# Node75 Codex Status · 键盘状态灯与额度菜单栏

让 NuPhy Node75 LP 左上角的点阵，在 **2.4G 无线连接**下提示 Codex 的运行、等待确认和完成状态；同时在 Mac 菜单栏显示 Codex 账户的剩余使用额度。

这是一个个人开发的 macOS 小工具，提供原生 AppKit 界面、独立灯光后台和软件内接入设置。关闭面板后仍可继续联动，无需一直打开 NuPhyIO。

[下载安装版](https://github.com/zerowangyu/node75-codex-status/releases/latest) · [完整使用说明](docs/使用说明.md) · [常见问题](docs/常见问题.md) · [源码构建](docs/开发说明.md)

## 能做什么

- **无线状态灯**：控制 Esc 上方点阵的第 1、3、5 列白灯，慢闪表示运行，快闪表示待回应，常亮表示完成。
- **多聊天协调**：待回应优先于运行；一个聊天完成时，不会清掉另一个聊天的运行状态。
- **菜单栏剩余额度**：显示官方接口返回的 5 小时／每周剩余百分比，每 5 分钟刷新，支持手动刷新和查看重置时间。
- **软件内接入**：安装／修复后台和 7 个 Hook，检查配置、信任、启用与访问权限，打开官方 Hook 审阅入口。
- **随时控制**：预览灯效、暂停／恢复、设置菜单栏登录启动、解除 Codex 接入。

菜单栏默认只显示键盘图标和剩余额度，不显示“运行中”等文字。状态详情仍可从菜单和控制面板查看。

## 支持范围

| 项目 | 当前支持 |
| --- | --- |
| 系统 | macOS 12 或更高，Apple Silicon（M 系列） |
| 键盘 | NuPhy **Node75 LP**，通过 2.4G 接收器连接 |
| 已验证硬件 | 键盘固件 1.0.10.6；接收器固件 4.0.5.6，VID:PID `19f5:2620` |
| 运行依赖 | Python 3.8+；本机已登录、支持 Hook 的官方 Codex CLI |
| 已验证 CLI | `0.162.0-alpha.2`；Hook 和 app-server 接口更新可能需要适配 |
| 发布包 | Apple Silicon 原生 `.app`，含后台安装资源；本地签名，未经 Apple 公证 |

**控制的是左上角点阵，不是按键背光。** 无线通道目前只能让这一组白灯同时亮灭，不支持自定义颜色、逐列控制、亮度渐变或官方呼吸／流光模式。Air75、其他 NuPhy 型号、蓝牙、有线控制、Intel Mac 和 Windows 尚未验证，不应视为已支持。

## 快速开始

1. 从 [Releases](https://github.com/zerowangyu/node75-codex-status/releases/latest) 下载 `Node75-Status-v1.3.1-macOS-arm64.zip`，解压，将 `Node75 Status.app` 放到 `~/Applications` 或 `/Applications`，然后打开。
2. 确保本机有 Python 3.8+，官方 Codex CLI 已安装并登录。键盘切到无线模式，按 **Fn + 4** 选择 2.4G，并插入接收器。
3. 在软件的 **Codex 接入设置 → 安装或修复接入** 中完成安装。程序保留已有的其他 Hook；修改配置前会备份。
4. 点 **打开官方 Hook 审阅**，在打开的 Codex CLI 输入 `/hooks`，审阅并信任新增的 7 个 Hook。这一步由官方 Codex 完成。
5. 按 macOS 提示授予灯光后台所需的“输入监控”权限。在接入页“重新检查”，再从菜单预览慢闪／快闪／常亮。
6. 在已加载这些 Hook 的 Codex 中开始新一轮对话，观察状态灯。已有会话若未加载配置，请重新打开会话或重启 Codex。

安装包未经过 Apple 公证，macOS 可能要求你在“系统设置 → 隐私与安全性”中确认打开。也可以按 [开发说明](docs/开发说明.md) 在本机从源码构建。首次 Hook 信任与 macOS 权限仍需本人操作。

## 灯光规则

| Codex 状态 | 点阵表现 |
| --- | --- |
| 正在运行 | 每 0.8 秒切换亮／灭，慢闪 |
| 等待权限确认或受支持的提问工具 | 每 0.2 秒切换亮／灭，快闪 |
| 本轮完成 | 常亮 10 秒 |
| 空闲、中断、退出 | 恢复系统指示灯状态 |

提问等待支持 `request_user_input` 与 `request_user_input_async`；普通聊天正文中的问句不会产生独立等待事件。菜单中的预览持续 5 秒，结束后恢复真实任务状态。

控制器只发送 HID 指示灯输出，不发送按键，也不改变系统 Caps Lock。联动期间，这组灯被用于任务提示，不能同时作为大写锁定指示；空闲和正常退出时会尝试恢复。

## 额度与关闭方式

额度属于整个 Codex 账户，按 `100 − usedPercent` 计算，不是当前聊天的上下文剩余容量。只显示接口实际返回的窗口；没有 5 小时额度时可只显示周额度，菜单注明“暂未提供”。刷新失败保留旧数据并标记 `*`，重置时间按北京时间显示。

| 操作 | 效果 |
| --- | --- |
| 关闭控制面板 | 菜单栏、额度刷新与灯光后台继续运行 |
| 退出菜单栏（灯光继续运行） | 关闭界面并停止额度轮询，灯光后台继续运行 |
| 关闭灯光联动并退出 | 关闭界面并停止灯光后台；后台下次登录仍会启动 |
| 暂停灯光联动 | 临时停用后台，可恢复；下次登录仍会启动 |
| 解除 Codex 接入 | 移除本程序的 Hook 与灯光后台登录项，保留界面、额度功能和其他 Hook |
| 完整停用 | 按 [使用说明](docs/使用说明.md#停用与卸载) 移除本程序的两个登录项和 Hook |

## 隐私与实现

灯光事件只在本机通过 Unix socket 传递。Hook 只传事件名称、聊天／轮次标识和等待标记，不保存提示词、聊天正文或工具参数，不返回权限审批决定。安装器不会修改 Hook 信任记录。

额度通过已登录的官方 `codex app-server` 只读接口查询；程序不直接读取登录凭据，不发起模型任务。额度查询由官方 Codex 联系 OpenAI；本程序仅缓存百分比、窗口长度和刷新／重置时间。软件没有额外遥测服务。[更多实现细节](docs/开发说明.md)

## 从源码构建

需要 Apple Silicon Mac、Python 3.8+ 和 Apple Command Line Tools：

```sh
xcode-select --install
python3 -B build_release.py
python3 -B -m unittest discover -s . -p 'test_*.py' -v
"Node75 Status.app/Contents/MacOS/Node75MenuBar" --self-test
codesign --verify --deep --strict "Node75 Status.app"
```

构建会生成 `Node75 Status.app`；不会安装后台、修改 Hook 或更改已有安装。安装包构建、架构说明与排障命令见 [开发说明](docs/开发说明.md)。

## 开源与反馈

采用 [MIT License](LICENSE)。欢迎在 [Issues](https://github.com/zerowangyu/node75-codex-status/issues) 反馈问题，附上系统、键盘／接收器固件和 Codex CLI 版本；分享日志前请移除个人路径、会话标识和其他私人信息。

这是独立个人项目，与 NuPhy 或 OpenAI 无官方关联。灵感来自 [Keyphore](https://github.com/BarryBarrywu/Keyphore)；HID 诊断参考 MIT 项目 [codex-kick75-status-lights](https://github.com/Pixelmoss/codex-kick75-status-lights) 与 [nuphyctl](https://github.com/fldc/nuphyctl)。未复制 Keyphore 的 GPL 源码。

相关链接：[NuPhy Node 系列](https://nuphy.com/products/nuphy-node-series-low-profile-page) · [Codex Hook 官方说明](https://learn.chatgpt.com/docs/hooks)
