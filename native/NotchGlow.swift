import AppKit

struct NotchGeometry {
    let screen: NSScreen
    let left: CGFloat
    let right: CGFloat
    let depth: CGFloat

    var width: CGFloat { right - left }

    static func find() -> NotchGeometry? {
        for screen in NSScreen.screens {
            guard let leftArea = screen.auxiliaryTopLeftArea,
                  let rightArea = screen.auxiliaryTopRightArea,
                  screen.safeAreaInsets.top > 0 else {
                continue
            }
            let left = leftArea.maxX - screen.frame.minX
            let right = rightArea.minX - screen.frame.minX
            guard right > left else { continue }
            return NotchGeometry(
                screen: screen,
                left: left,
                right: right,
                depth: screen.safeAreaInsets.top
            )
        }
        return nil
    }
}

final class GlowView: NSView {
    var drawsGlow = true
    var notchWidth: CGFloat = 0
    var notchDepth: CGFloat = 0
    var glowColor = NSColor.systemOrange
    var intensity: CGFloat = 0
    var mode = "idle" { didSet { needsLayout = true; needsDisplay = true } }
    var callName = "TalkToMe" { didSet { nameField.stringValue = callName } }
    var muted = false { didSet { needsLayout = true } }
    var onAction: ((String) -> Void)?
    var onMove: (() -> Void)?
    var callStartedAt: TimeInterval?
    private let nameField = NSTextField(labelWithString: "TalkToMe")
    private let hintField = NSTextField(labelWithString: "Incoming call")
    private let timerField = NSTextField(labelWithString: "00:00")
    private var buttons: [NSButton] = []
    private var panelWidth: CGFloat = 280
    private var panelHeight: CGFloat = 0
    private var active: Bool { !drawsGlow && !["idle", "hover", "ending"].contains(mode) }
    var controlsVisible: Bool { panelHeight > 0.1 }
    var notchCenter: CGFloat = 0
    override var isFlipped: Bool { true }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        nameField.font = .systemFont(ofSize: 12, weight: .medium)
        nameField.textColor = .white
        nameField.lineBreakMode = .byTruncatingTail
        hintField.font = .systemFont(ofSize: 10)
        hintField.textColor = .secondaryLabelColor
        addSubview(nameField)
        addSubview(hintField)
        timerField.font = .monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        timerField.textColor = NSColor(white: 1, alpha: 0.9)
        timerField.alignment = .center
        timerField.setAccessibilityLabel("Call duration")
        timerField.toolTip = "Drag to move the call controls"
        nameField.toolTip = "Drag to move the call controls"
        addSubview(timerField)
        let items = [("xmark", "Decline call"), ("phone.fill", "Answer call"),
                     ("text.bubble", "Open transcript"), ("mic.fill", "Mute microphone"),
                     ("phone.down.fill", "End call")]
        for (index, item) in items.enumerated() {
            let button = NSButton(image: NSImage(systemSymbolName: item.0, accessibilityDescription: item.1)!, target: self, action: #selector(pressed(_:)))
            button.tag = index
            button.isBordered = false
            button.contentTintColor = .white
            button.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 13, weight: .medium)
            button.setAccessibilityLabel(item.1)
            button.toolTip = item.1
            button.wantsLayer = true
            button.layer?.cornerRadius = 15
            button.layer?.backgroundColor = (index == 1 ? NSColor.systemBlue : index == 4 ? NSColor.systemRed : NSColor(white: 0.10, alpha: 1)).cgColor
            addSubview(button)
            buttons.append(button)
        }
    }

    required init?(coder: NSCoder) { fatalError("Use init(frame:).") }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard !drawsGlow else { return nil }
        let hit = super.hitTest(point)
        if hit === nameField || hit === hintField || hit === timerField { return self }
        return hit
    }

    override func mouseDown(with event: NSEvent) {
        guard containsControls(convert(event.locationInWindow, from: nil)) else { return }
        window?.performDrag(with: event)
        onMove?()
    }

    @objc private func pressed(_ sender: NSButton) {
        onAction?(["decline", "accept", "transcript", "mute", "end"][sender.tag])
    }

    func advance(_ elapsed: Double) {
        let factor = CGFloat(1 - exp(-elapsed * 15))
        let height: CGFloat = active ? (mode == "ringing" ? 64 : 56) : 0
        panelHeight += (height - panelHeight) * factor
        panelWidth += ((mode == "ringing" ? 320 : 280) - panelWidth) * factor
        if let callStartedAt {
            let seconds = max(0, Int(ProcessInfo.processInfo.systemUptime - callStartedAt))
            let text = String(format: "%02d:%02d", seconds / 60, seconds % 60)
            if timerField.stringValue != text { timerField.stringValue = text }
        }
        for item in subviews { item.alphaValue = min(1, max(0, (panelHeight - height + 12) / 12)) }
        needsLayout = true
        needsDisplay = true
    }

    override func layout() {
        super.layout()
        if drawsGlow {
            for item in subviews { item.isHidden = true }
            return
        }
        let ringing = mode == "ringing"
        nameField.isHidden = !ringing
        hintField.isHidden = !ringing
        timerField.isHidden = !active || ringing
        timerField.frame = NSRect(x: notchCenter - 122, y: 18, width: 88, height: 20)
        nameField.frame = NSRect(x: notchCenter - 136, y: 13, width: 162, height: 18)
        hintField.frame = NSRect(x: notchCenter - 136, y: 33, width: 162, height: 16)
        let offsets: [CGFloat] = [52, 98, 2, 44, 86]
        for (index, button) in buttons.enumerated() {
            button.isHidden = index < 2 ? !ringing : !active || ringing
            button.frame = NSRect(x: notchCenter + offsets[index], y: index < 2 ? 17 : 13, width: 30, height: 30)
        }
        let isMuted = muted || mode == "muted"
        let label = isMuted ? "Unmute microphone" : "Mute microphone"
        buttons[3].image = NSImage(systemSymbolName: isMuted ? "mic.slash.fill" : "mic.fill", accessibilityDescription: label)
        buttons[3].setAccessibilityLabel(label)
        buttons[3].contentTintColor = isMuted ? .systemRed : .white
    }

    private func callPath() -> NSBezierPath {
        NSBezierPath(roundedRect: NSRect(x: notchCenter - panelWidth / 2, y: 0,
            width: panelWidth, height: panelHeight), xRadius: panelHeight / 2, yRadius: panelHeight / 2)
    }

    func containsControls(_ point: NSPoint) -> Bool { active && callPath().contains(point) }

    // The shoulders stay beside the camera. The lower edge follows its depth.
    private func notchPath(includeWings: Bool = true) -> NSBezierPath {
        let left = notchCenter - notchWidth / 2
        let right = notchCenter + notchWidth / 2
        let shoulderY: CGFloat = 0.5
        let bottom = notchDepth + 0.5
        let path = NSBezierPath()
        path.move(to: NSPoint(x: includeWings ? 0 : left - 65, y: shoulderY))
        path.line(to: NSPoint(x: left - 65, y: shoulderY))
        path.curve(to: NSPoint(x: left - 0.75, y: bottom),
                   controlPoint1: NSPoint(x: left - 20, y: shoulderY),
                   controlPoint2: NSPoint(x: left - 50, y: bottom))
        path.line(to: NSPoint(x: right + 0.75, y: bottom))
        path.curve(to: NSPoint(x: right + 65, y: shoulderY),
                   controlPoint1: NSPoint(x: right + 50, y: bottom),
                   controlPoint2: NSPoint(x: right + 20, y: shoulderY))
        path.line(to: NSPoint(x: includeWings ? bounds.width : right + 65, y: shoulderY))
        return path
    }

    private func taper(_ context: CGContext, left: CGFloat, right: CGFloat, feather: CGFloat) {
        let fraction = min(0.45, feather / (right - left))
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
            colors: [NSColor.clear.cgColor, NSColor.white.cgColor,
                     NSColor.white.cgColor, NSColor.clear.cgColor] as CFArray,
            locations: [0, fraction, 1 - fraction, 1])!
        context.setBlendMode(.destinationIn)
        context.drawLinearGradient(gradient, start: NSPoint(x: left, y: 0),
            end: NSPoint(x: right, y: 0), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        context.setBlendMode(.normal)
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        if panelHeight > 0.1 {
            NSColor(white: 0, alpha: 0.96).setFill()
            callPath().fill()
        }
        guard drawsGlow && intensity > 0.005 else { return }
        context.saveGState()
        context.beginTransparencyLayer(auxiliaryInfo: nil)
        let edge = notchPath()
        edge.lineCapStyle = .round
        edge.lineJoinStyle = .round
        // Add a soft light below the edge without moving the bright core.
        let downwardGlow = edge.copy() as! NSBezierPath
        let offset = AffineTransform(translationByX: 0, byY: 6)
        downwardGlow.transform(using: offset)
        var previousDownwardOpacity: CGFloat = 0
        for step in stride(from: 96, through: 2, by: -2) {
            let radius = CGFloat(step) / 2
            let opacity = 0.18 * intensity * exp(-(radius * radius) / 512)
            let alpha = (opacity - previousDownwardOpacity) / (1 - previousDownwardOpacity)
            glowColor.withAlphaComponent(alpha).setStroke()
            downwardGlow.lineWidth = CGFloat(step)
            downwardGlow.stroke()
            previousDownwardOpacity = opacity
        }
        // Draw the light around the camera and along the screen edge.
        var previousOpacity: CGFloat = 0
        for step in stride(from: 72, through: 2, by: -1) {
            let radius = CGFloat(step) / 2
            let opacity = 0.68 * intensity * exp(-(radius * radius) / 200)
            let alpha = (opacity - previousOpacity) / (1 - previousOpacity)
            glowColor.withAlphaComponent(alpha).setStroke()
            edge.lineWidth = CGFloat(step)
            edge.stroke()
            previousOpacity = opacity
        }
        glowColor.withAlphaComponent(0.9 * intensity).setStroke()
        edge.lineWidth = 2.0
        edge.stroke()
        let mask = notchPath(includeWings: false)
        mask.line(to: NSPoint(x: notchCenter + notchWidth / 2 + 65, y: 0))
        mask.line(to: NSPoint(x: notchCenter - notchWidth / 2 - 65, y: 0))
        mask.close()
        NSColor.black.setFill()
        mask.fill()
        let coreOpacity = !["idle", "hover", "ending", "muted"].contains(mode)
            ? 0.86 + 0.12 * intensity : min(1, intensity * 1.18)
        glowColor.withAlphaComponent(coreOpacity).setStroke()
        edge.lineWidth = 0.9
        edge.stroke()
        let glowReach = notchWidth / 2 + 160
        taper(context, left: notchCenter - glowReach,
              right: notchCenter + glowReach, feather: 95)
        context.endTransparencyLayer()
        context.restoreGState()
    }
}

final class NotchGlowDelegate: NSObject, NSApplicationDelegate {
    private var panel: NSPanel?
    private var glowView: GlowView?
    private var callPanel: NSPanel?
    private var callView: GlowView?
    private var notch: NotchGeometry?
    private var mode = "idle"
    private var callName = "TalkToMe"
    private var callStartedAt: TimeInterval?
    private var callID = ""
    private var ringID = ""
    private var draggedPillFrame: NSRect?
    private var muted = false
    private var probeMode = false
    private var previewItem: NSStatusItem?
    private var previewWindow: NSWindow?
    private var previewState: NSPopUpButton?
    private var previewTranscript: NSWindow?
    private var ringTimer: Timer?
    private let ringSound = NSSound(
        contentsOf: URL(fileURLWithPath: "/System/Library/Sounds/Ping.aiff"),
        byReference: true
    )
    private var selectedColor = "amber"
    private var intensity: CGFloat = 0
    private var lastFrameTime = Date.timeIntervalSinceReferenceDate

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        probeMode = CommandLine.arguments.contains("--probe")
            || URL(fileURLWithPath: CommandLine.arguments[0]).lastPathComponent == "NotchGlowProbe"
        showGlow()
        if probeMode {
            mode = "connected"
            callName = "Codex"
            syncView()
            showPreviewControls()
        } else {
            DispatchQueue.global(qos: .utility).async { [weak self] in
                while let line = readLine() {
                    guard let data = line.data(using: .utf8),
                          let command = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
                        continue
                    }
                    DispatchQueue.main.async { self?.setState(command) }
                }
                DispatchQueue.main.async { NSApp.terminate(nil) }
            }
        }
        Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            self?.updateGlow()
        }
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(screenChanged),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
    }

    @objc private func screenChanged() {
        showGlow()
    }

    private func setState(_ command: [String: String]) {
        let wasRinging = mode == "ringing"
        let previousRingID = ringID
        if let next = command["callId"], next != callID {
            callID = next
            callStartedAt = nil
        }
        if let next = command["ringId"] { ringID = next }
        if let text = command["startedAt"], let timestamp = Double(text), timestamp.isFinite, timestamp > 0 {
            let duration = max(0, Date().timeIntervalSince1970 - timestamp)
            callStartedAt = ProcessInfo.processInfo.systemUptime - duration
        }
        let validModes = ["idle", "hover", "ringing", "connected", "listening", "thinking", "speaking", "muted", "ending"]
        if let next = command["mode"], validModes.contains(next) { mode = next }
        let validColors = ["amber", "blue", "violet", "green", "pink", "cyan"]
        if let next = command["color"], validColors.contains(next) { selectedColor = next }
        if let next = command["name"] { callName = String(next.prefix(80)) }
        if let next = command["muted"] { muted = next == "true" }
        if wasRinging != (mode == "ringing") || previousRingID != ringID { updateRing() }
        syncView()
    }

    private func updateRing() {
        ringTimer?.invalidate()
        ringTimer = nil
        ringSound?.stop()
        guard mode == "ringing" && !probeMode else { return }
        ringSound?.volume = 0.30
        ringSound?.play()
        let stopAt = ProcessInfo.processInfo.systemUptime + 10
        ringTimer = Timer.scheduledTimer(withTimeInterval: 2.3, repeats: true) { [weak self] _ in
            self?.ringSound?.stop()
            if ProcessInfo.processInfo.systemUptime >= stopAt {
                self?.ringTimer?.invalidate()
                self?.ringTimer = nil
                return
            }
            self?.ringSound?.play()
        }
    }

    private func syncView() {
        if ["connected", "listening", "thinking", "speaking", "muted"].contains(mode) {
            if callStartedAt == nil { callStartedAt = ProcessInfo.processInfo.systemUptime }
        } else {
            callStartedAt = nil
        }
        for view in [glowView, callView].compactMap({ $0 }) {
            view.callStartedAt = callStartedAt
            view.mode = mode
            view.callName = callName
            view.muted = muted
        }
    }

    private func handleAction(_ action: String) {
        if probeMode {
            if action == "accept" { mode = "connected" }
            if action == "end" || action == "decline" { mode = "ending" }
            if action == "mute" { muted.toggle() }
            if action == "transcript" {
                if previewTranscript == nil {
                    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 240), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                    window.title = "Transcript — Preview"
                    window.isReleasedWhenClosed = false
                    let text = NSTextField(wrappingLabelWithString: "CODEX\nWhat would you like to work on?\n\nYOU\nLet us examine the notch design.")
                    text.frame = NSRect(x: 20, y: 20, width: 340, height: 200)
                    text.autoresizingMask = [.width, .height]
                    window.contentView?.addSubview(text)
                    window.center()
                    previewTranscript = window
                }
                previewTranscript?.makeKeyAndOrderFront(nil)
            }
            previewState?.selectItem(withTitle: mode.capitalized)
            syncView()
            return
        }
        if let data = try? JSONSerialization.data(withJSONObject: ["action": action]) {
            FileHandle.standardOutput.write(data + Data([0x0a]))
        }
    }

    private func updateGlow() {
        let now = Date.timeIntervalSinceReferenceDate
        let elapsed = min(now - lastFrameTime, 0.1)
        lastFrameTime = now
        let hovering: Bool
        if let notch {
            let pointer = NSEvent.mouseLocation
            let center = notch.screen.frame.minX + (notch.left + notch.right) / 2
            hovering = abs(pointer.x - center) < notch.width / 2 + 22
                && pointer.y > notch.screen.frame.maxY - notch.depth - 30
        } else {
            hovering = false
        }
        let color: NSColor
        let target: CGFloat
        switch mode {
        case "ringing":
            color = selectedGlowColor()
            target = 0.80 + 0.12 * sin(now * 3.5)
        case "listening":
            color = .white
            target = 0.70 + 0.08 * sin(now * 2.1)
        case "thinking":
            color = NSColor(calibratedRed: 0.64, green: 0.24, blue: 1, alpha: 1)
            target = 0.70 + 0.08 * sin(now * 1.8)
        case "speaking":
            color = selectedGlowColor()
            target = 0.86 + 0.07 * sin(now * 2.6)
        case "muted":
            color = selectedGlowColor()
            target = 0.16
        case "connected":
            color = NSColor(white: 0.95, alpha: 1)
            target = 0.56
        case "hover":
            color = selectedGlowColor()
            target = 0.40
        case "ending":
            color = selectedGlowColor()
            target = 0
        default:
            color = selectedGlowColor()
            target = hovering ? 0.30 : 0
        }
        glowView?.advance(elapsed)
        callView?.advance(elapsed)
        if let panel = callPanel, let view = callView {
            let local = view.convert(panel.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            panel.ignoresMouseEvents = !view.containsControls(local)
            if view.controlsVisible {
                if !panel.isVisible { panel.orderFrontRegardless() }
            } else {
                panel.orderOut(nil)
            }
        }
        let previousIntensity = intensity
        intensity += (target - intensity) * min(1, CGFloat(elapsed) * 7)
        if abs(target - intensity) < 0.002 { intensity = target }
        guard abs(previousIntensity - intensity) > 0.001
                || glowView?.glowColor.isEqual(color) == false else { return }
        glowView?.glowColor = glowView?.glowColor.blended(withFraction: min(1, CGFloat(elapsed) * 9), of: color) ?? color
        glowView?.intensity = intensity
        glowView?.needsDisplay = true
    }

    private func showPreviewControls() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 218),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "TalkToMe — Silent preview"
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        window.center()
        let content = window.contentView!
        let title = NSTextField(labelWithString: "Notch glow")
        title.font = .systemFont(ofSize: 19, weight: .semibold)
        title.frame = NSRect(x: 24, y: 170, width: 370, height: 28)
        content.addSubview(title)
        let hint = NSTextField(labelWithString: "No call, microphone, or agent connection.")
        hint.textColor = .secondaryLabelColor
        hint.frame = NSRect(x: 24, y: 145, width: 370, height: 20)
        content.addSubview(hint)
        let states = NSPopUpButton(frame: NSRect(x: 24, y: 95, width: 180, height: 30))
        states.addItems(withTitles: ["Idle", "Hover", "Ringing", "Connected", "Listening", "Thinking", "Speaking", "Muted", "Ending"])
        states.selectItem(withTitle: "Connected")
        states.target = self
        states.action = #selector(previewStateChanged(_:))
        states.setAccessibilityLabel("Preview state")
        content.addSubview(states)
        previewState = states
        let colors = NSPopUpButton(frame: NSRect(x: 216, y: 95, width: 180, height: 30))
        colors.addItems(withTitles: ["Amber", "Blue", "Violet", "Green", "Pink", "Cyan"])
        colors.target = self
        colors.action = #selector(previewColorChanged(_:))
        colors.setAccessibilityLabel("Glow color")
        content.addSubview(colors)
        let close = NSButton(title: "Close preview", target: self, action: #selector(closePreview))
        close.bezelStyle = .rounded
        close.frame = NSRect(x: 260, y: 24, width: 136, height: 32)
        content.addSubview(close)
        let show = NSButton(title: "Show notch", target: self, action: #selector(showPreviewSurface))
        show.bezelStyle = .rounded
        show.frame = NSRect(x: 24, y: 24, width: 136, height: 32)
        content.addSubview(show)
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "Notch preview"
        let menu = NSMenu()
        for state in ["Idle", "Hover", "Ringing", "Connected", "Listening", "Thinking", "Speaking", "Muted", "Ending"] {
            let entry = NSMenuItem(title: state, action: #selector(previewMenuState(_:)), keyEquivalent: "")
            entry.target = self
            menu.addItem(entry)
        }
        menu.addItem(.separator())
        let controls = NSMenuItem(title: "Preview controls", action: #selector(openPreviewControls), keyEquivalent: "")
        controls.target = self
        menu.addItem(controls)
        let quit = NSMenuItem(title: "Close preview", action: #selector(closePreview), keyEquivalent: "")
        quit.target = self
        menu.addItem(quit)
        item.menu = menu
        previewItem = item
        window.makeKeyAndOrderFront(nil)
        previewWindow = window
    }

    @objc private func previewStateChanged(_ sender: NSPopUpButton) {
        mode = sender.titleOfSelectedItem!.lowercased()
        muted = mode == "muted"
        syncView()
    }

    @objc private func previewColorChanged(_ sender: NSPopUpButton) {
        selectedColor = sender.titleOfSelectedItem!.lowercased()
    }

    @objc private func showPreviewSurface() {
        previewWindow?.orderOut(nil)
        panel?.orderFrontRegardless()
    }

    @objc private func openPreviewControls() { previewWindow?.makeKeyAndOrderFront(nil) }

    @objc private func previewMenuState(_ sender: NSMenuItem) {
        mode = sender.title.lowercased()
        muted = mode == "muted"
        previewState?.selectItem(withTitle: sender.title)
        syncView()
        showPreviewSurface()
    }

    @objc private func closePreview() { NSApp.terminate(nil) }

    private func selectedGlowColor() -> NSColor {
        switch selectedColor {
        case "blue": return NSColor(calibratedRed: 0.12, green: 0.55, blue: 1, alpha: 1)
        case "violet": return NSColor(calibratedRed: 0.64, green: 0.24, blue: 1, alpha: 1)
        case "green": return NSColor(calibratedRed: 0.14, green: 0.96, blue: 0.44, alpha: 1)
        case "pink": return NSColor(calibratedRed: 1, green: 0.20, blue: 0.61, alpha: 1)
        case "cyan": return NSColor(calibratedRed: 0.08, green: 0.90, blue: 1, alpha: 1)
        default: return NSColor(calibratedRed: 1, green: 0.58, blue: 0.16, alpha: 1)
        }
    }

    private func showGlow() {
        panel?.orderOut(nil)
        callPanel?.orderOut(nil)
        callPanel = nil
        callView = nil
        panel = nil
        glowView = nil
        notch = NotchGeometry.find()
        guard let notch else {
            emit(["event": "unavailable"])
            return
        }

        let width = notch.screen.frame.width
        let height = notch.depth + 100
        let frame = NSRect(
            x: notch.screen.frame.minX,
            y: notch.screen.frame.maxY - height,
            width: width,
            height: height
        )
        let panel = NSPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false,
            screen: notch.screen
        )
        panel.title = "Notch surface"
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        panel.level = .popUpMenu
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        let view = GlowView(frame: NSRect(origin: .zero, size: frame.size))
        view.notchWidth = notch.width
        view.notchDepth = notch.depth
        view.notchCenter = (notch.left + notch.right) / 2
        view.intensity = intensity
        view.mode = mode
        view.callName = callName
        view.muted = muted
        view.callStartedAt = callStartedAt
        view.onAction = { [weak self] action in self?.handleAction(action) }
        panel.contentView = view
        panel.orderFrontRegardless()
        self.panel = panel
        glowView = view

        let pillSize = NSSize(width: 352, height: 64)
        let cameraCenter = notch.screen.frame.minX + (notch.left + notch.right) / 2
        // Leave space below the lowest part of the glow.
        let pillTop = notch.screen.frame.maxY - notch.depth - 64
        let pillFrame = NSRect(x: cameraCenter - pillSize.width / 2,
                               y: pillTop - pillSize.height,
                               width: pillSize.width, height: pillSize.height)
        let pill = NSPanel(contentRect: pillFrame, styleMask: [.borderless, .nonactivatingPanel],
                           backing: .buffered, defer: false, screen: notch.screen)
        pill.title = "Call controls"
        pill.isOpaque = false
        pill.backgroundColor = .clear
        pill.hasShadow = false
        pill.ignoresMouseEvents = true
        pill.hidesOnDeactivate = false
        pill.level = .popUpMenu
        pill.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        if let saved = draggedPillFrame {
            let display = NSScreen.screens.max(by: {
                $0.frame.intersection(saved).width * $0.frame.intersection(saved).height <
                $1.frame.intersection(saved).width * $1.frame.intersection(saved).height
            }) ?? notch.screen
            let area = display.visibleFrame
            pill.setFrameOrigin(NSPoint(x: max(area.minX, min(saved.minX, area.maxX - pillSize.width)),
                                        y: max(area.minY, min(saved.minY, area.maxY - pillSize.height))))
        }
        let controls = GlowView(frame: NSRect(origin: .zero, size: pillFrame.size))
        controls.drawsGlow = false
        controls.notchCenter = pillFrame.width / 2
        controls.onAction = { [weak self] action in self?.handleAction(action) }
        controls.onMove = { [weak self] in
            self?.draggedPillFrame = self?.callPanel?.frame
            self?.reportPillBounds()
        }
        pill.contentView = controls
        callPanel = pill
        callView = controls
        syncView()
        emit(["event": "ready", "geometry": [
            "screenX": notch.screen.frame.minX,
            "screenWidth": notch.screen.frame.width,
            "notchDepth": notch.depth,
        ]])
        reportPillBounds()
    }

    private func emit(_ message: [String: Any]) {
        guard !probeMode, let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        FileHandle.standardOutput.write(data + Data([0x0a]))
    }

    private func reportPillBounds() {
        guard let frame = callPanel?.frame, let primary = NSScreen.screens.first else { return }
        emit(["event": "pill-bounds", "bounds": [
            "x": frame.minX, "y": primary.frame.maxY - frame.maxY,
            "width": frame.width, "height": frame.height,
        ]])
    }
}

if CommandLine.arguments.contains("--geometry") {
    if let notch = NotchGeometry.find() {
        let screen = notch.screen
        let data: [String: Double] = [
            "screenX": Double(screen.frame.minX),
            "screenY": Double(screen.frame.minY),
            "screenWidth": Double(screen.frame.width),
            "screenHeight": Double(screen.frame.height),
            "notchLeft": Double(notch.left),
            "notchRight": Double(notch.right),
            "notchDepth": Double(notch.depth),
        ]
        let bytes = try! JSONSerialization.data(withJSONObject: data, options: [.sortedKeys])
        print(String(data: bytes, encoding: .utf8)!)
    } else {
        print("{\"notch\":false}")
    }
} else {
    let app = NSApplication.shared
    let delegate = NotchGlowDelegate()
    app.delegate = delegate
    app.run()
}
