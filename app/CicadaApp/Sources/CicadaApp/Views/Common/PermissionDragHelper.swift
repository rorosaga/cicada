import AppKit
import SwiftUI

// G218 — the one way Cicada asks for a macOS privacy permission it cannot ask for in a dialog: a small floating panel
// says what is needed in one line with one Open button; Open deep-links to the exact list in System Settings; a second
// card, placed over System Settings, holds Cicada's own icon and name as a tile the person drags straight into that
// list. A gentle poll (preflight only — `CGPreflightScreenCaptureAccess`, `AXIsProcessTrusted`) notices the switch and
// both panels close by themselves.
//
// **Never a prompting API.** Nothing here calls `CGRequestScreenCaptureAccess`, `AXIsProcessTrustedWithOptions` with
// its prompt, or touches ScreenCaptureKit: the probe is `TracePermissionProbe`, which has no asking method at all. The
// opener, the probe and the clock are injected, so tests never open System Settings and never read a real permission.
//
// Design direction D: depth is a ring, not a shadow (DR-9/DR-10 — the panel's own window shadow is off and only the
// theme's floating surface draws); SF type through the theme ladder (DR-15/16); the one accent is the Open button,
// the surface's one primary action (DR-5.2); no motion of its own, so Reduce Motion has nothing to soften (DR-66).

/// Opens a System Settings pane. Live: `NSWorkspace.open`.
@MainActor
protocol PermissionSettingsOpener {
    func open(_ url: URL)
}

struct LivePermissionSettingsOpener: PermissionSettingsOpener {
    func open(_ url: URL) { NSWorkspace.shared.open(url) }
}

/// A repeating tick the poll runs on. Live: a run-loop `Timer`.
@MainActor
protocol PermissionPollClock {
    /// Calls `tick` every `interval` seconds until the returned token is cancelled.
    func every(_ interval: TimeInterval, _ tick: @escaping @MainActor () -> Void) -> PermissionPollToken
}

@MainActor
protocol PermissionPollToken: AnyObject {
    func cancel()
}

struct LivePermissionPollClock: PermissionPollClock {
    func every(_ interval: TimeInterval, _ tick: @escaping @MainActor () -> Void) -> PermissionPollToken {
        let timer = Timer(timeInterval: interval, repeats: true) { _ in MainActor.assumeIsolated { tick() } }
        timer.tolerance = interval * 0.25
        RunLoop.main.add(timer, forMode: .common)
        return TimerToken(timer: timer)
    }

    private final class TimerToken: PermissionPollToken {
        let timer: Timer
        init(timer: Timer) { self.timer = timer }
        func cancel() { timer.invalidate() }
        deinit { timer.invalidate() }
    }
}

/// The helper's state, with no AppKit in it: which pane Open goes to, the words, and the poll that ticks the step.
@MainActor
@Observable
final class PermissionDragHelperModel {
    enum Phase: Equatable {
        /// The panel shows; Open not pressed yet (the poll already runs: the person may allow it some other way).
        case asking
        /// System Settings was opened; the drag card shows.
        case opened
        case granted
        case cancelled
    }

    let kind: TracePermission
    private(set) var phase: Phase = .asking

    /// The step ticks (once).
    @ObservationIgnored var onGranted: (() -> Void)?
    /// Both panels close: granted or cancelled.
    @ObservationIgnored var onFinish: (() -> Void)?
    /// After each poll that found nothing yet (the live controller re-places the drag card over System Settings).
    @ObservationIgnored var onPoll: (() -> Void)?

    @ObservationIgnored private let probe: any TracePermissionProbe
    @ObservationIgnored private let opener: any PermissionSettingsOpener
    @ObservationIgnored private let clock: any PermissionPollClock
    @ObservationIgnored private let interval: TimeInterval
    @ObservationIgnored private var token: PermissionPollToken?

    init(kind: TracePermission, probe: any TracePermissionProbe, opener: any PermissionSettingsOpener,
         clock: any PermissionPollClock, interval: TimeInterval = CicadaTiming.permissionPoll) {
        self.kind = kind
        self.probe = probe
        self.opener = opener
        self.clock = clock
        self.interval = interval
    }

    var need: String { Copy.Traces.need(kind) }
    var hint: String { Copy.Traces.nearMiss(kind) }
    var isFinished: Bool { phase == .granted || phase == .cancelled }

    /// The exact list in System Settings (Privacy & Security), by its deep link.
    static func settingsURL(for kind: TracePermission) -> URL {
        let anchor = switch kind {
        case .screenRecording: "Privacy_ScreenCapture"
        case .accessibility: "Privacy_Accessibility"
        case .fullDiskAccess: "Privacy_AllFiles"
        }
        // swiftlint:disable:next force_unwrapping
        return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!
    }

    /// Shows the step: already allowed → ticks at once; otherwise the poll starts.
    func start() {
        guard !isFinished else { return }
        if probe.granted(kind) { finish(granted: true); return }
        poll()
    }

    /// The panel's Open: the exact list in System Settings, and the drag card.
    func open() {
        guard !isFinished else { return }
        opener.open(Self.settingsURL(for: kind))
        phase = .opened
        poll()
    }

    /// One look, by preflight. The clock calls it; tests call it directly.
    func tick() {
        guard !isFinished else { return }
        if probe.granted(kind) { finish(granted: true) } else { onPoll?() }
    }

    func cancel() {
        guard !isFinished else { return }
        finish(granted: false)
    }

    private func poll() {
        guard token == nil else { return }
        token = clock.every(interval) { [weak self] in self?.tick() }
    }

    private func finish(granted: Bool) {
        token?.cancel()
        token = nil
        phase = granted ? .granted : .cancelled
        if granted { onGranted?() }
        onFinish?()
    }
}

// MARK: - The live panels

/// A panel that floats over System Settings without taking the keyboard from it.
private final class PermissionHelperPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// The two floating panels around one `PermissionDragHelperModel`. One helper at a time: presenting another closes the
/// first (as cancelled).
@MainActor
final class PermissionDragHelper {
    private static var current: PermissionDragHelper?

    let model: PermissionDragHelperModel
    private var askPanel: NSPanel?
    private var dragPanel: NSPanel?

    private init(model: PermissionDragHelperModel) { self.model = model }

    /// Shows the helper for `kind`. `onGranted` runs once, when the preflight says yes; the panels then close.
    @discardableResult
    static func present(kind: TracePermission, probe: any TracePermissionProbe = LiveTracePermissionProbe(),
                        onGranted: @escaping () -> Void) -> PermissionDragHelperModel {
        current?.model.cancel()
        let model = PermissionDragHelperModel(kind: kind, probe: probe, opener: LivePermissionSettingsOpener(),
                                              clock: LivePermissionPollClock())
        let helper = PermissionDragHelper(model: model)
        current = helper
        model.onGranted = onGranted
        model.onFinish = { [weak helper] in
            helper?.closePanels()
            if current === helper { current = nil }
        }
        model.onPoll = { [weak helper] in helper?.placeDragCard() }
        model.start()
        if !model.isFinished { helper.showAskPanel() }
        return model
    }

    private static func makePanel() -> NSPanel {
        let panel = PermissionHelperPanel(contentRect: .zero, styleMask: [.nonactivatingPanel, .borderless],
                                          backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false   // depth is a ring, not a shadow (DR-9)
        panel.isMovableByWindowBackground = true
        return panel
    }

    private func showAskPanel() {
        let panel = Self.makePanel()
        let host = NSHostingView(rootView: PermissionAskCard(model: model, onOpen: { [weak self] in
            self?.model.open()
            self?.showDragCard()
        }))
        panel.contentView = host
        let size = host.fittingSize
        let visible = NSScreen.main?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 876)
        panel.setFrame(CGRect(x: visible.midX - size.width / 2, y: visible.maxY - size.height - 24,
                              width: size.width, height: size.height), display: false)
        panel.orderFrontRegardless()
        askPanel = panel
    }

    private func showDragCard() {
        guard dragPanel == nil, !model.isFinished else { return }
        let panel = Self.makePanel()
        panel.isMovableByWindowBackground = false   // a drag on it is the app tile's drag
        let host = NSHostingView(rootView: PermissionDragCard(appURL: Bundle.main.bundleURL,
                                                              name: Self.appName,
                                                              icon: NSWorkspace.shared.icon(forFile: Bundle.main.bundlePath)))
        panel.contentView = host
        panel.setContentSize(host.fittingSize)
        dragPanel = panel
        placeDragCard()
        panel.orderFrontRegardless()
        // System Settings takes a moment to open its list: place the card again once it has.
        DispatchQueue.main.asyncAfter(deadline: .now() + CicadaTiming.permissionPoll) { [weak self] in
            self?.placeDragCard()
        }
    }

    /// Over System Settings' window, at its lower left (the sidebar, beside the list it is dragged into); under the ask
    /// panel when that window is not found. Window bounds only — no title, no permission.
    private func placeDragCard() {
        guard let panel = dragPanel else { return }
        let size = panel.frame.size
        if let settings = Self.systemSettingsFrame() {
            panel.setFrameOrigin(CGPoint(x: settings.minX + 16, y: settings.minY + 16))
        } else if let ask = askPanel?.frame {
            panel.setFrameOrigin(CGPoint(x: ask.midX - size.width / 2, y: ask.minY - size.height - 12))
        }
    }

    private func closePanels() {
        askPanel?.orderOut(nil)
        dragPanel?.orderOut(nil)
        askPanel = nil
        dragPanel = nil
    }

    static var appName: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
            ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String)
            ?? ProcessInfo.processInfo.processName
    }

    /// System Settings' front window, in AppKit coordinates.
    static func systemSettingsFrame() -> CGRect? {
        guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.systempreferences").first,
              let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
                as? [[String: Any]] else { return nil }
        let pid = app.processIdentifier
        for info in list {
            guard (info[kCGWindowOwnerPID as String] as? Int).map(pid_t.init) == pid,
                  (info[kCGWindowLayer as String] as? Int) == 0,
                  let bounds = info[kCGWindowBounds as String] as? [String: CGFloat],
                  let x = bounds["X"], let y = bounds["Y"], let w = bounds["Width"], let h = bounds["Height"],
                  w > 200, h > 200 else { continue }
            let primary = NSScreen.screens.first?.frame.height ?? 0
            return CGRect(x: x, y: primary - y - h, width: w, height: h)
        }
        return nil
    }
}

// MARK: - The two cards

/// The ask: one line of what is needed, the near-miss hint, Open, and ×.
private struct PermissionAskCard: View {
    let model: PermissionDragHelperModel
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                Text(model.need)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.spacingSM)
                IconButton(systemName: "xmark", help: Copy.Traces.closeHelper, accessibilityLabel: Copy.Traces.closeHelper) {
                    model.cancel()
                }
            }
            Text(model.hint)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                PrimaryActionButton(title: Copy.Traces.open, action: onOpen)
                    .help(Copy.Traces.openHelp)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: CicadaTheme.scaled(340), alignment: .leading)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .padding(CicadaTheme.spacingXL)   // room for the light theme's one soft shadow inside the clear window
    }
}

/// Cicada's own icon and name: drag it into the list.
private struct PermissionDragCard: View {
    let appURL: URL
    let name: String
    let icon: NSImage

    var body: some View {
        VStack(spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(nsImage: icon)
                    .resizable()
                    .frame(width: CicadaTheme.scaled(36), height: CicadaTheme.scaled(36))
                    .accessibilityHidden(true)
                Text(name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgButton))
            .ringed(.strong, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .overlay(AppTileDragSource(url: appURL))
            Text(Copy.Traces.dragHint)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingSM)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .padding(CicadaTheme.spacingXL)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Copy.Traces.dragHint)
    }
}

/// The tile's drag: the app bundle as a file URL, the way Finder drags an app — what System Settings' lists accept.
private struct AppTileDragSource: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> DragSourceView { DragSourceView(url: url) }
    func updateNSView(_ view: DragSourceView, context: Context) { view.url = url }

    final class DragSourceView: NSView, NSDraggingSource {
        var url: URL

        init(url: URL) {
            self.url = url
            super.init(frame: .zero)
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

        override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

        override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }

        override func mouseDragged(with event: NSEvent) {
            let item = NSDraggingItem(pasteboardWriter: url as NSURL)
            let icon = NSWorkspace.shared.icon(forFile: url.path)
            icon.size = NSSize(width: 48, height: 48)
            let point = convert(event.locationInWindow, from: nil)
            item.setDraggingFrame(CGRect(x: point.x - 24, y: point.y - 24, width: 48, height: 48), contents: icon)
            beginDraggingSession(with: [item], event: event, source: self)
        }

        func draggingSession(_ session: NSDraggingSession,
                             sourceOperationMaskFor context: NSDraggingContext) -> NSDragOperation {
            context == .outsideApplication ? [.copy, .link, .generic] : []
        }
    }
}
