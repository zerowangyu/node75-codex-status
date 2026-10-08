// SPDX-License-Identifier: MIT
import AppKit

struct LampStatus {
    let state: String
    let hardware: String
    let sessions: Int
    let preview: Bool
    static func decode(_ data: Data) -> LampStatus? {
        guard let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let state = value["state"] as? String,
              ["idle", "running", "attention", "completed"].contains(state),
              let hardware = value["hardware"] as? String,
              let sessions = value["sessions"] as? Int, sessions >= 0 else { return nil }
        return LampStatus(state: state, hardware: hardware, sessions: sessions,
                          preview: value["preview"] as? Bool ?? false)
    }
    var title: String {
        switch state {
        case "running": return "运行中"
        case "attention": return "等待确认"
        case "completed": return "已完成"
        default: return "空闲"
        }
    }
}

struct QuotaWindow {
    let name: String
    let short: String
    let remaining: Double
    let minutes: Int?
    let resets: Double?
    var percent: String { String(format: "%.0f%%", remaining) }
}
struct QuotaStatus {
    let windows: [QuotaWindow]
    let updated: Double?
    let stale: Bool
    static func decode(_ data: Data) -> QuotaStatus? {
        guard let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let rows = value["windows"] as? [[String: Any]] else { return nil }
        let windows = rows.compactMap { row -> QuotaWindow? in
            guard let name = row["name"] as? String, let short = row["short"] as? String,
                  let percent = row["remainingPercent"] as? Double, percent.isFinite,
                  percent >= 0, percent <= 100 else { return nil }
            return QuotaWindow(name: name, short: short, remaining: percent,
                               minutes: row["windowDurationMins"] as? Int, resets: row["resetsAt"] as? Double)
        }
        let updated = value["updatedAt"] as? Double
        let old = updated.map { Date().timeIntervalSince1970 - $0 > 600 } ?? true
        return QuotaStatus(windows: windows, updated: updated, stale: (value["stale"] as? Bool ?? false) || old)
    }
    var compact: String {
        if windows.isEmpty { return "额度--" }
        return windows.map { "\($0.short)\($0.percent)" }.joined(separator: " ") + (stale ? "*" : "")
    }
}

final class MenuBar: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let home = FileManager.default.homeDirectoryForCurrentUser
    var root: URL { home.appendingPathComponent("Library/Application Support/Node75Codex") }
    var plist: URL { home.appendingPathComponent("Library/LaunchAgents/local.node75.codex-status.plist") }
    var loginPlist: URL { home.appendingPathComponent("Library/LaunchAgents/local.node75.codex-menubar.plist") }
    var domain: String { "gui/\(getuid())" }
    let label = "local.node75.codex-status"
    var item: NSStatusItem!
    let menu = NSMenu()
    var statusLine: NSMenuItem!
    var hardwareLine: NSMenuItem!
    var sessionsLine: NSMenuItem!
    var toggle: NSMenuItem!
    var previewMenu: NSMenuItem!
    var cancelPreview: NSMenuItem!
    var closeAll: NSMenuItem!
    var login: NSMenuItem!
    var timer: Timer?
    var busy = false
    var live = false
    var panel: NSWindow?
    var panelStatus: NSTextField?
    var panelHardware: NSTextField?
    var panelSessions: NSTextField?
    var panelToggle: NSButton?
    var panelPreviews = [NSButton]()
    var panelQuota: NSTextField?
    var quota5hLine: NSMenuItem!
    var quotaWeekLine: NSMenuItem!
    var quotaOtherLine: NSMenuItem!
    var quotaUpdatedLine: NSMenuItem!
    var quotaRefresh: NSMenuItem!
    var quotaBusy = false
    var lastQuotaRequest: TimeInterval = 0
    var setupPanel: NSWindow?
    var hooksPanel: NSWindow?
    var setupLines = [NSTextField]()
    var setupInstall: NSButton?
    var setupCheck: NSButton?
    var setupReview: NSButton?
    var setupDefinitions: NSButton?
    var setupDisconnect: NSButton?
    var setupChecking = false
    var lastSetupRequest: TimeInterval = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let identifier = Bundle.main.bundleIdentifier,
           NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
            .contains(where: { !$0.isTerminated && $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            NSApp.terminate(nil)
            return
        }
        NSApp.setActivationPolicy(.accessory)
        if !UserDefaults.standard.bool(forKey: "quotaOnlyMenuBarDefaultV1") {
            UserDefaults.standard.set(true, forKey: "hideStateText")
            UserDefaults.standard.set(true, forKey: "quotaOnlyMenuBarDefaultV1")
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = item.button {
            let image = NSImage(systemSymbolName: "keyboard", accessibilityDescription: "Node75 状态灯")
            image?.isTemplate = true
            button.image = image
            button.imagePosition = .imageLeading
        }
        menu.autoenablesItems = false
        menu.delegate = self
        statusLine = add("Node75 状态灯", action: nil)
        hardwareLine = add("正在读取连接状态…", action: nil)
        sessionsLine = add("", action: nil)
        menu.addItem(.separator())
        quota5hLine = add("5 小时：读取中…", action: nil)
        quotaWeekLine = add("每周：读取中…", action: nil)
        quotaOtherLine = add("", action: nil)
        quotaUpdatedLine = add("使用额度属于整个 Codex 账户", action: nil)
        quotaRefresh = add("刷新使用额度", action: #selector(refreshQuota))
        let quotaDisplay = add("图标旁显示剩余额度", action: #selector(toggleQuota(_:)))
        quotaDisplay.state = showQuota ? .on : .off
        menu.addItem(.separator())
        add("打开控制面板…", action: #selector(openPanel))
        add("Codex 接入设置…", action: #selector(openSetup))
        toggle = add("暂停灯光联动", action: #selector(toggleService))
        previewMenu = add("预览灯效（5 秒）", action: nil)
        previewMenu.isEnabled = true
        let previews = NSMenu()
        previews.autoenablesItems = false
        for (name, mode) in [("慢闪 · 运行中", "running"), ("快闪 · 等待确认", "attention"), ("常亮 · 已完成", "completed")] {
            let row = NSMenuItem(title: name, action: #selector(preview(_:)), keyEquivalent: "")
            row.target = self
            row.representedObject = mode
            previews.addItem(row)
        }
        previewMenu.submenu = previews
        cancelPreview = add("结束预览，恢复真实状态", action: #selector(endPreview))
        menu.addItem(.separator())
        login = add("登录时显示菜单栏", action: #selector(toggleLogin))
        let text = add("菜单栏显示状态文字", action: #selector(toggleText(_:)))
        text.state = showText ? .on : .off
        add("查看使用说明", action: #selector(openHelp))
        add("打开运行日志", action: #selector(openLog))
        menu.addItem(.separator())
        closeAll = add("关闭灯光联动并退出", action: #selector(stopAndQuit))
        add("退出菜单栏（灯光继续运行）", action: #selector(quit))
        item.menu = menu
        refresh()
        timer = Timer(timeInterval: 1, target: self, selector: #selector(refresh), userInfo: nil, repeats: true)
        timer?.tolerance = 0.2
        RunLoop.main.add(timer!, forMode: .common)
        if !FileManager.default.fileExists(atPath: plist.path) {
            openSetup()
        } else if CommandLine.arguments.contains("--show-panel") ||
            ProcessInfo.processInfo.environment["XPC_SERVICE_NAME"] != "local.node75.codex-menubar" ||
            !UserDefaults.standard.bool(forKey: "hasShownPanel") {
            openPanel()
            UserDefaults.standard.set(true, forKey: "hasShownPanel")
        }
        checkSetup()
    }

    @discardableResult func add(_ title: String, action: Selector?) -> NSMenuItem {
        let row = NSMenuItem(title: title, action: action, keyEquivalent: "")
        row.target = self
        row.isEnabled = action != nil
        menu.addItem(row)
        return row
    }
    var showText: Bool { !UserDefaults.standard.bool(forKey: "hideStateText") }
    var showQuota: Bool { !UserDefaults.standard.bool(forKey: "hideQuota") }
    func menuWillOpen(_ menu: NSMenu) { refresh() }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openPanel()
        return true
    }

    func dateText(_ timestamp: Double, format: String) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.timeZone = TimeZone(identifier: "Asia/Shanghai")
        formatter.dateFormat = format
        return formatter.string(from: Date(timeIntervalSince1970: timestamp))
    }
    func quotaDescription(_ window: QuotaWindow?) -> String {
        guard let window = window else { return "暂未提供" }
        var text = "剩余 \(window.percent)"
        if let reset = window.resets { text += " · \(dateText(reset, format: "M月d日 HH:mm")) 重置" }
        return text
    }

    @objc func refresh() {
        let installed = FileManager.default.fileExists(atPath: plist.path)
        live = installed && FileManager.default.fileExists(atPath: root.appendingPathComponent("status.sock").path)
        let state = (try? Data(contentsOf: root.appendingPathComponent("status.json"))).flatMap(LampStatus.decode)
        let quota = (try? Data(contentsOf: root.appendingPathComponent("quota.json"))).flatMap(QuotaStatus.decode)
        let title = live ? (state?.title ?? "启动中") : (installed ? "已暂停" : "未安装")
        var parts = [String]()
        if showQuota { parts.append(quota?.compact ?? "额度…") }
        if showText { parts.append(title) }
        item.button?.title = parts.isEmpty ? "" : " " + parts.joined(separator: " · ")
        item.button?.toolTip = "Node75 状态灯 · \(title) · 剩余额度 \(quota?.compact ?? "读取中")\(quota?.stale == true ? "（上次记录）" : "")"
        statusLine.title = "Node75 · \(title)\(state?.preview == true && live ? "（预览）" : "")"
        if !live {
            hardwareLine.title = installed ? "点阵恢复系统指示灯" : "请先运行安装程序"
        } else if state?.hardware == "connected" {
            hardwareLine.title = "2.4G 接收器已连接"
        } else if state?.hardware == "idle" || state?.state == "idle" {
            hardwareLine.title = "2.4G 待命 · 空闲时释放控制"
        } else {
            hardwareLine.title = "正在连接 2.4G 接收器…"
        }
        sessionsLine.title = live ? "活动聊天：\(state?.sessions ?? 0)" : "暂停后不接收任务状态；恢复后等待新事件"
        toggle.title = busy ? "正在处理…" : (live ? "暂停灯光联动" : "恢复灯光联动")
        toggle.isEnabled = installed && !busy
        previewMenu.isEnabled = live && !busy
        cancelPreview.isEnabled = live && !busy && state?.preview == true
        closeAll.isEnabled = !busy
        login.state = FileManager.default.fileExists(atPath: loginPlist.path) ? .on : .off
        let shortWindow = quota?.windows.first { $0.minutes == 300 }
        let weekWindow = quota?.windows.first { $0.minutes == 10080 }
        quota5hLine.title = "5 小时：" + quotaDescription(shortWindow)
        quotaWeekLine.title = "每周：" + quotaDescription(weekWindow)
        let otherWindows = quota?.windows.filter { $0.minutes != 300 && $0.minutes != 10080 } ?? []
        quotaOtherLine.isHidden = otherWindows.isEmpty
        quotaOtherLine.title = otherWindows.map { "\($0.name)：\(quotaDescription($0))" }.joined(separator: "；")
        if let updated = quota?.updated {
            quotaUpdatedLine.title = "\(quota?.stale == true ? "上次记录" : "额度更新")：\(dateText(updated, format: "M月d日 HH:mm"))（北京时间）"
        } else { quotaUpdatedLine.title = "额度暂不可用；使用当前 Codex 登录状态" }
        quotaRefresh.title = quotaBusy ? "正在刷新使用额度…" : "刷新使用额度（每 5 分钟自动更新）"
        quotaRefresh.isEnabled = !quotaBusy
        panelStatus?.stringValue = title + (state?.preview == true && live ? " · 预览" : "")
        panelHardware?.stringValue = hardwareLine.title
        panelSessions?.stringValue = sessionsLine.title
        panelToggle?.title = toggle.title
        panelToggle?.isEnabled = toggle.isEnabled
        panelPreviews.forEach { $0.isEnabled = live && !busy }
        panelQuota?.stringValue = "账户剩余额度 · \(quota?.compact ?? "读取中…")\(quota?.stale == true ? "（上次记录）" : "")"
        refreshSetup()
        if setupPanel?.isVisible == true && !setupChecking && !busy && Date().timeIntervalSince1970-lastSetupRequest >= 60 { checkSetup() }
        if !quotaBusy && Date().timeIntervalSince1970-lastQuotaRequest >= 300 { refreshQuota() }
    }

    @objc func openPanel() {
        if panel == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 400),
                                  styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Node75 状态灯"
            window.isReleasedWhenClosed = false
            let stack = NSStackView()
            stack.orientation = .vertical
            stack.alignment = .centerX
            stack.spacing = 14
            stack.translatesAutoresizingMaskIntoConstraints = false
            let heading = NSTextField(labelWithString: "Node75 · Codex 状态灯")
            heading.font = .systemFont(ofSize: 17, weight: .semibold)
            stack.addArrangedSubview(heading)
            panelStatus = NSTextField(labelWithString: "")
            panelStatus?.font = .systemFont(ofSize: 28, weight: .medium)
            stack.addArrangedSubview(panelStatus!)
            panelHardware = NSTextField(labelWithString: "")
            panelHardware?.textColor = .secondaryLabelColor
            stack.addArrangedSubview(panelHardware!)
            panelSessions = NSTextField(labelWithString: "")
            panelSessions?.font = .systemFont(ofSize: 11)
            panelSessions?.textColor = .secondaryLabelColor
            stack.addArrangedSubview(panelSessions!)
            panelQuota = NSTextField(labelWithString: "")
            panelQuota?.font = .systemFont(ofSize: 13, weight: .medium)
            stack.addArrangedSubview(panelQuota!)
            let setup = NSButton(title: "Codex 接入设置…", target: self, action: #selector(openSetup))
            setup.bezelStyle = .rounded
            stack.addArrangedSubview(setup)
            panelToggle = NSButton(title: "暂停灯光联动", target: self, action: #selector(toggleService))
            panelToggle?.bezelStyle = .rounded
            stack.addArrangedSubview(panelToggle!)
            let previews = NSStackView()
            previews.orientation = .horizontal
            previews.spacing = 10
            for (title, mode) in [("预览慢闪", "running"), ("预览快闪", "attention"), ("预览常亮", "completed")] {
                let button = NSButton(title: title, target: self, action: #selector(previewButton(_:)))
                button.bezelStyle = .rounded
                button.identifier = NSUserInterfaceItemIdentifier(mode)
                panelPreviews.append(button)
                previews.addArrangedSubview(button)
            }
            stack.addArrangedSubview(previews)
            let caption = NSTextField(labelWithString: "预览 5 秒后恢复真实状态。关闭窗口不停止灯光联动。")
            caption.font = .systemFont(ofSize: 11)
            caption.textColor = .secondaryLabelColor
            stack.addArrangedSubview(caption)
            window.contentView!.addSubview(stack)
            NSLayoutConstraint.activate([
                stack.centerXAnchor.constraint(equalTo: window.contentView!.centerXAnchor),
                stack.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor),
                stack.leadingAnchor.constraint(greaterThanOrEqualTo: window.contentView!.leadingAnchor, constant: 16),
                stack.trailingAnchor.constraint(lessThanOrEqualTo: window.contentView!.trailingAnchor, constant: -16)
            ])
            window.center()
            panel = window
        }
        refresh()
        NSApp.activate(ignoringOtherApps: true)
        panel?.makeKeyAndOrderFront(nil)
    }
    @objc func previewButton(_ sender: NSButton) {
        if let mode = sender.identifier?.rawValue { sendPreview(mode) }
    }

    func pythonExecutable() throws -> String {
        if let data = try? Data(contentsOf: root.appendingPathComponent("menubar-config.json")),
           let config = (try? JSONSerialization.jsonObject(with: data)) as? [String: String],
           let python = config["python"], FileManager.default.isExecutableFile(atPath: python) { return python }
        for python in ["/opt/homebrew/opt/python@3.12/bin/python3.12", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            if FileManager.default.isExecutableFile(atPath: python),
               (try? run(python, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)"])) != nil { return python }
        }
        throw NSError(domain: "Node75", code: 1, userInfo: [NSLocalizedDescriptionKey: "这台 Mac 需要 Python 3.8 或更新版本，请安装后重试。"])
    }
    func payloadScript(_ name: String) throws -> String {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("Payload/"+name),
              FileManager.default.fileExists(atPath: url.path) else {
            throw NSError(domain: "Node75", code: 1, userInfo: [NSLocalizedDescriptionKey: "软件安装资源不完整，请重新打开完整的 Node75 Status.app。"])
        }
        return url.path
    }
    @objc func refreshQuota() {
        guard !quotaBusy else { return }
        quotaBusy = true
        lastQuotaRequest = Date().timeIntervalSince1970
        refresh()
        DispatchQueue.global(qos: .utility).async {
            try? self.run(self.pythonExecutable(), ["-B", self.payloadScript("usage.py"), "refresh"])
            DispatchQueue.main.async { self.quotaBusy = false; self.refresh() }
        }
    }
    @objc func toggleQuota(_ sender: NSMenuItem) {
        UserDefaults.standard.set(showQuota, forKey: "hideQuota")
        sender.state = showQuota ? .on : .off
        refresh()
    }

    @objc func openSetup() {
        if setupPanel == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: 460),
                                  styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Codex 接入设置"
            window.isReleasedWhenClosed = false
            let stack = NSStackView()
            stack.orientation = .vertical
            stack.alignment = .leading
            stack.spacing = 14
            stack.translatesAutoresizingMaskIntoConstraints = false
            let heading = NSTextField(labelWithString: "连接 Codex 与 Node75")
            heading.font = .systemFont(ofSize: 20, weight: .semibold)
            stack.addArrangedSubview(heading)
            let guide = NSTextField(labelWithString: "安装接入 → 在 Codex 信任 Hook → 开始一轮对话")
            guide.textColor = .secondaryLabelColor
            stack.addArrangedSubview(guide)
            for _ in 0..<5 {
                let line = NSTextField(labelWithString: "正在检查…")
                line.font = .systemFont(ofSize: 13)
                setupLines.append(line)
                stack.addArrangedSubview(line)
            }
            func row(_ buttons: [NSButton]) {
                let row = NSStackView(views: buttons)
                row.orientation = .horizontal
                row.spacing = 10
                buttons.forEach { $0.bezelStyle = .rounded }
                stack.addArrangedSubview(row)
            }
            setupInstall = NSButton(title: "安装或修复接入", target: self, action: #selector(installIntegration))
            setupCheck = NSButton(title: "重新检查", target: self, action: #selector(checkSetup))
            row([setupInstall!, setupCheck!])
            setupReview = NSButton(title: "打开官方 Hook 审阅", target: self, action: #selector(reviewHooks))
            setupDefinitions = NSButton(title: "查看已配置 Hook", target: self, action: #selector(showHooks))
            row([setupReview!, setupDefinitions!])
            let permissions = NSButton(title: "打开输入监控设置", target: self, action: #selector(openInputMonitoring))
            setupDisconnect = NSButton(title: "解除 Codex 接入", target: self, action: #selector(disconnectIntegration))
            row([permissions, setupDisconnect!])
            let caption = NSTextField(labelWithString: "官方审阅打开后输入 /hooks。已信任的定义无需重复确认。")
            caption.font = .systemFont(ofSize: 11)
            caption.textColor = .secondaryLabelColor
            stack.addArrangedSubview(caption)
            window.contentView!.addSubview(stack)
            NSLayoutConstraint.activate([
                stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
                stack.trailingAnchor.constraint(lessThanOrEqualTo: window.contentView!.trailingAnchor, constant: -28),
                stack.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor)
            ])
            window.center()
            setupPanel = window
        }
        NSApp.activate(ignoringOtherApps: true)
        setupPanel?.makeKeyAndOrderFront(nil)
        refreshSetup()
        checkSetup()
    }

    func setupData() -> [String: Any]? {
        guard let data = try? Data(contentsOf: root.appendingPathComponent("integration.json")) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    func refreshSetup() {
        let data = setupData()
        let configured = data?["configured"] as? Int
        let installed = FileManager.default.fileExists(atPath: plist.path)
        let receipt = (try? Data(contentsOf: root.appendingPathComponent("hook-receipt.json")))
            .flatMap { (try? JSONSerialization.jsonObject(with: $0)) as? [String: Any] }
        if setupLines.count == 5 {
            setupLines[0].stringValue = "后台服务：" + (installed ? (live ? "已安装 · 运行中" : "已安装 · 已暂停") : "未安装")
            setupLines[1].stringValue = "状态 Hook：" + (configured.map { "\($0) / 7 已配置" } ?? "尚未检查")
            if let trusted = data?["trusted"] as? Int, let active = data?["active"] as? Int {
                setupLines[2].stringValue = "Codex 信任：\(trusted) / 7 已信任，\(active) / 7 已启用"
            } else { setupLines[2].stringValue = "Codex 信任：" + (data?["trustError"] as? String ?? "正在核实官方状态…") }
            if let permission = data?["inputMonitoring"] as? Bool {
                setupLines[3].stringValue = "键盘访问权限：" + (permission ? "已允许" : "需在系统输入监控中允许")
            } else { setupLines[3].stringValue = "键盘访问权限：安装后可核验" }
            if let timestamp = receipt?["receivedAt"] as? Double, let event = receipt?["event"] as? String {
                let names = ["UserPromptSubmit":"任务开始", "PreToolUse":"工具执行", "PostToolUse":"工具完成",
                             "PermissionRequest":"等待确认", "Stop":"任务结束", "Interrupt":"任务中断", "SessionEnd":"会话退出"]
                setupLines[4].stringValue = "最近收到事件：\(dateText(timestamp, format: "M月d日 HH:mm:ss")) · \(names[event] ?? "状态更新")"
            } else { setupLines[4].stringValue = "最近收到事件：暂无；完成信任后开始一轮对话" }
            if let error = data?["configurationError"] as? String { setupLines[1].stringValue = "状态 Hook："+error }
        }
        setupInstall?.title = busy ? "正在处理…" : "安装或修复接入"
        setupInstall?.isEnabled = !busy && !setupChecking
        setupCheck?.title = setupChecking ? "正在检查…" : "重新检查"
        setupCheck?.isEnabled = !busy && !setupChecking
        setupReview?.isEnabled = !busy && (data?["codexAvailable"] as? Bool ?? false)
        setupDefinitions?.isEnabled = (configured ?? 0) > 0
        setupDisconnect?.isEnabled = !busy && installed
    }
    @objc func checkSetup() {
        guard !setupChecking && !busy else { return }
        setupChecking = true
        lastSetupRequest = Date().timeIntervalSince1970
        refreshSetup()
        DispatchQueue.global(qos: .utility).async {
            var failure: Error?
            do { try self.run(self.pythonExecutable(), ["-B", self.payloadScript("integration.py"), "inspect"]) }
            catch { failure = error }
            DispatchQueue.main.async {
                self.setupChecking = false
                self.refreshSetup()
                if let error = failure, self.setupLines.count == 5 {
                    self.setupLines[2].stringValue = "接入检查："+error.localizedDescription
                }
            }
        }
    }
    @objc func installIntegration() {
        perform({ try self.run(self.pythonExecutable(), ["-B", self.payloadScript("install.py"), "integrate"]) },
                completion: { self.lastQuotaRequest = 0; self.checkSetup(); self.refresh() })
    }
    @objc func disconnectIntegration() {
        let alert = NSAlert()
        alert.messageText = "解除 Codex 接入？"
        alert.informativeText = "停止灯光后台并移除本程序的 7 个 Hook，保留其他 Hook、菜单栏和额度显示。可以随时重新安装接入。"
        alert.addButton(withTitle: "解除接入")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        perform({ try self.run(self.pythonExecutable(), ["-B", self.payloadScript("install.py"), "disconnect"]) },
                completion: { self.checkSetup() })
    }
    @objc func reviewHooks() {
        perform({ try self.run(self.pythonExecutable(), ["-B", self.payloadScript("integration.py"), "review-terminal"]) })
    }
    @objc func openInputMonitoring() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")!)
    }
    @objc func showHooks() {
        guard let text = setupData()?["definitions"] as? String else { return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 460),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Node75 已配置的状态 Hook（仅本程序）"
        window.isReleasedWhenClosed = false
        let scroll = NSScrollView(frame: window.contentView!.bounds)
        scroll.autoresizingMask = [.width, .height]
        scroll.hasVerticalScroller = true
        let view = NSTextView(frame: scroll.bounds)
        view.autoresizingMask = [.width]
        view.isEditable = false
        view.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        view.textContainerInset = NSSize(width: 12, height: 12)
        view.string = text
        scroll.documentView = view
        window.contentView!.addSubview(scroll)
        window.center()
        hooksPanel?.close()
        hooksPanel = window
        window.makeKeyAndOrderFront(nil)
    }

    func run(_ executable: String, _ arguments: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let output = Pipe()
        process.standardOutput = FileHandle.nullDevice
        process.standardError = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let message = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "操作失败"
            throw NSError(domain: "Node75", code: Int(process.terminationStatus),
                          userInfo: [NSLocalizedDescriptionKey: message])
        }
    }

    func perform(_ work: @escaping () throws -> Void, completion: (() -> Void)? = nil) {
        guard !busy else { return }
        busy = true
        refresh()
        DispatchQueue.global(qos: .userInitiated).async {
            var failure: Error?
            do { try work() } catch { failure = error }
            DispatchQueue.main.async {
                self.busy = false
                self.refresh()
                if let failure = failure {
                    let alert = NSAlert()
                    alert.messageText = "未完成操作"
                    alert.informativeText = failure.localizedDescription
                    alert.addButton(withTitle: "知道了")
                    NSApp.activate(ignoringOtherApps: true)
                    alert.runModal()
                } else { completion?() }
            }
        }
    }

    func pause() throws {
        // The service handles SIGTERM and restores the keyboard before closing.
        if (try? run("/bin/launchctl", ["print", "\(domain)/\(label)"])) != nil {
            try run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
            for _ in 0..<60 {
                if !FileManager.default.fileExists(atPath: root.appendingPathComponent("status.sock").path) { return }
                Thread.sleep(forTimeInterval: 0.1)
            }
            throw NSError(domain: "Node75", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "后台仍在退出，请稍后再试。"])
        }
    }

    @objc func toggleService() {
        let shouldPause = live
        perform({
            if shouldPause { try self.pause() }
            else {
                if (try? self.run("/bin/launchctl", ["print", "\(self.domain)/\(self.label)"])) == nil {
                    var lastError: Error?
                    for _ in 0..<20 {
                        do {
                            try self.run("/bin/launchctl", ["bootstrap", self.domain, self.plist.path])
                            return
                        } catch { lastError = error; Thread.sleep(forTimeInterval: 0.25) }
                    }
                    if let error = lastError { throw error }
                }
            }
        })
    }

    func sendPreview(_ mode: String) {
        perform({
            let data = try Data(contentsOf: self.plist)
            guard let config = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
                  let arguments = config["ProgramArguments"] as? [String], let python = arguments.first else {
                throw NSError(domain: "Node75", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "无法读取后台运行配置。"])
            }
            try self.run(python, ["-B", self.root.appendingPathComponent("node75_status.py").path,
                                 "preview", "--mode", mode])
        })
    }
    @objc func preview(_ sender: NSMenuItem) {
        if let mode = sender.representedObject as? String { sendPreview(mode) }
    }
    @objc func endPreview() { sendPreview("idle") }
    @objc func toggleText(_ sender: NSMenuItem) {
        UserDefaults.standard.set(showText, forKey: "hideStateText")
        sender.state = showText ? .on : .off
        refresh()
    }
    @objc func toggleLogin() {
        do {
            if FileManager.default.fileExists(atPath: loginPlist.path) {
                try FileManager.default.removeItem(at: loginPlist)
            } else if let executable = Bundle.main.executablePath {
                let configuration: [String: Any] = ["Label": "local.node75.codex-menubar",
                    "ProgramArguments": [executable], "RunAtLoad": true,
                    "StandardOutPath": root.appendingPathComponent("menubar.log").path,
                    "StandardErrorPath": root.appendingPathComponent("menubar.log").path]
                let data = try PropertyListSerialization.data(fromPropertyList: configuration, format: .xml, options: 0)
                try FileManager.default.createDirectory(at: loginPlist.deletingLastPathComponent(), withIntermediateDirectories: true)
                try data.write(to: loginPlist, options: .atomic)
            }
        } catch {
            let alert = NSAlert()
            alert.messageText = "无法保存登录设置"
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
        refresh()
    }
    @objc func openHelp() {
        if let url = Bundle.main.url(forResource: "README", withExtension: "md") { NSWorkspace.shared.open(url) }
    }
    @objc func openLog() { NSWorkspace.shared.open(root.appendingPathComponent("service.log")) }
    @objc func stopAndQuit() { perform({ try self.pause() }, completion: { NSApp.terminate(nil) }) }
    @objc func quit() { NSApp.terminate(nil) }
}

if CommandLine.arguments.contains("--self-test") {
    let sample = Data(#"{"state":"attention","hardware":"connected","sessions":2,"preview":true}"#.utf8)
    guard let status = LampStatus.decode(sample), status.title == "等待确认", status.sessions == 2, status.preview,
          LampStatus.decode(Data(#"{"state":"bogus","hardware":"connected","sessions":1}"#.utf8)) == nil,
          LampStatus.decode(Data("{}".utf8)) == nil else { exit(1) }
    let quotaSample = Data(#"{"windows":[{"name":"每周","short":"周","remainingPercent":87,"windowDurationMins":10080}],"updatedAt":0,"stale":true}"#.utf8)
    guard let quota = QuotaStatus.decode(quotaSample), quota.compact == "周87%*", quota.stale,
          QuotaStatus.decode(Data("{}".utf8)) == nil else { exit(1) }
    print("菜单栏状态与额度解析检查通过")
} else {
    let app = NSApplication.shared
    let delegate = MenuBar()
    app.delegate = delegate
    app.run()
}
