import AppKit
import SwiftUI

// G218 — the one way Cicada asks for a macOS privacy permission it cannot ask for in a dialog: ONE floating banner
// (owner 2026-11-03: "the banner with instructions has the logo itself and maybe bounces a bit at the start") holding the
// app's own icon — the drag source itself, the bundle as a file the way Finder drags an app — one line saying what to
// do, at most one action, and ×. Open deep-links to the exact list in System Settings and the banner moves over it. A
// gentle poll (preflight only — `CGPreflightScreenCaptureAccess`, `AXIsProcessTrusted`, a protected file's open) notices
// the switch and the banner closes by itself.
//
// **Never a prompting API.** Nothing here calls `CGRequestScreenCaptureAccess`, `AXIsProcessTrustedWithOptions` with
// its prompt, or touches ScreenCaptureKit: the probe is `TracePermissionProbe`, which has no asking method at all. The
// opener, the probe and the clock are injected, so tests never open System Settings and never read a real permission.
//
// Design direction D: depth is a ring, not a shadow (DR-9/DR-10 — the panel's own window shadow is off and only the
// theme's floating surface draws); SF type through the theme ladder (DR-15/16); one primary at most (DR-5.2); the icon's
// arrival hop is `CicadaMotion.helperBounce`, nothing under Reduce Motion (DR-66); DESIGN_RULES §9 2026-11-03.

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

/// What the ask panel tells the person to do (onboarding v3, 2026-10-24, after HeyClicky's recovery rows): two
/// instructions for two states, and the relaunch macOS sometimes needs before a grant shows.
enum PermissionAsk: Equatable {
    /// Cicada is not in the list yet: "Drag me into the … list."
    case drag
    /// Cicada has been in the list before (`PermissionMemory`), or the person came back from it: "Flip my toggle on."
    case flip
    /// Screen Recording or Full Disk Access, back from System Settings with the preflight still saying no: the switch may
    /// be on already and need a fresh process — "Already on? Reopen Cicada to apply it."
    case reopen
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
    let place: PermissionPlace
    /// The app's own name as the banner says it ("Drag Cicada into …"); live, the bundle's display name.
    let appName: String
    private(set) var phase: Phase = .asking
    /// The person came back to Cicada from System Settings and the preflight still says no.
    private(set) var returnedWithoutGrant = false

    /// The step ticks (once).
    @ObservationIgnored var onGranted: (() -> Void)?
    /// Both panels close: granted or cancelled.
    @ObservationIgnored var onFinish: (() -> Void)?
    /// After each poll that found nothing yet (the live controller re-places the drag card over System Settings).
    @ObservationIgnored var onPoll: (() -> Void)?

    @ObservationIgnored private let probe: any TracePermissionProbe
    @ObservationIgnored private let opener: any PermissionSettingsOpener
    @ObservationIgnored private let clock: any PermissionPollClock
    /// Nil (a test that does not pass one): nothing remembered, so every ask starts as a drag.
    @ObservationIgnored private let memory: PermissionMemory?
    @ObservationIgnored private let relauncher: (any AppRelauncher)?
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let interval: TimeInterval
    @ObservationIgnored private var token: PermissionPollToken?

    init(kind: TracePermission, probe: any TracePermissionProbe, opener: any PermissionSettingsOpener,
         clock: any PermissionPollClock, interval: TimeInterval = CicadaTiming.permissionPoll,
         place: PermissionPlace = .sources, memory: PermissionMemory? = nil,
         relauncher: (any AppRelauncher)? = nil, appName: String = "Cicada", now: @escaping () -> Date = Date.init) {
        self.kind = kind
        self.appName = appName
        self.probe = probe
        self.opener = opener
        self.clock = clock
        self.interval = interval
        self.place = place
        self.memory = memory
        self.relauncher = relauncher
        self.now = now
    }

    /// Toggle versus drag, and the relaunch case — from what the helper has seen, never from a prompting API.
    var ask: PermissionAsk {
        if returnedWithoutGrant, kind.needsRelaunch { return .reopen }
        if returnedWithoutGrant || memory?.inList(kind) == true { return .flip }
        return .drag
    }

    var need: String { Copy.Permission.line(kind, ask: ask, app: appName) }
    var isFinished: Bool { phase == .granted || phase == .cancelled }
    /// "Already on? Reopen Cicada" as the banner's one quiet action once System Settings is open, for the two kinds
    /// whose grant waits for a fresh process (HeyClicky's standing recovery line).
    var offersReopen: Bool { kind.needsRelaunch && phase == .opened && relauncher != nil }

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

    /// Cicada became the active app again. Only after Open: a look by preflight, and — still no — the panel's words move
    /// on to the toggle, or to the relaunch for a kind that needs one.
    func returned() {
        guard !isFinished, phase == .opened else { return }
        if probe.granted(kind) { finish(granted: true); return }
        returnedWithoutGrant = true
    }

    /// "Reopen Cicada": leaves the marker that brings the next launch back to this step, then quits and reopens.
    func reopen() {
        guard !isFinished, let relauncher else { return }
        token?.cancel()
        token = nil
        relauncher.relaunch(resume: PermissionResume(kind: kind, place: place, at: now()))
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
        if granted {
            memory?.noteGranted(kind)
            onGranted?()
        }
        onFinish?()
    }
}

/// A host row's control for one permission (Traces' steps and switches, the Full Disk Access fix under Messages and a
/// browser): its button until the helper shows; once the person closed the helper with ×, the row quietly becomes an
/// *Open* link that brings the helper back (HeyClicky: "this row will quietly switch to Open"); granted, it is done.
enum PermissionRowState: Equatable {
    case ask
    case retry
    case granted

    static func after(_ phase: PermissionDragHelperModel.Phase?, granted: Bool) -> PermissionRowState {
        if granted || phase == .granted { return .granted }
        return phase == .cancelled ? .retry : .ask
    }
}

// MARK: - The live panels

/// A panel that floats over System Settings without taking the keyboard from it.
private final class PermissionHelperPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// The one floating banner around one `PermissionDragHelperModel`. One helper at a time: presenting another closes
/// the first (as cancelled).
@MainActor
final class PermissionDragHelper {
    private static var current: PermissionDragHelper?

    let model: PermissionDragHelperModel
    private var panel: NSPanel?
    private var activeObserver: NSObjectProtocol?

    private init(model: PermissionDragHelperModel) { self.model = model }

    /// Shows the helper for `kind`. `onGranted` runs once, when the preflight says yes; the banner then closes.
    /// `onFinish(granted)` runs once either way, so a host row can turn into its *Open* link after ×. `place` is where a
    /// relaunch brings the person back (onboarding's steps, Traces, Settings, the Sources page). `openAtOnce` (the
    /// Permissions rows, owner 2026-11-03): the person's click already was the ask, so System Settings opens on the list
    /// with the banner over it at once.
    @discardableResult
    static func present(kind: TracePermission, probe: any TracePermissionProbe = LiveTracePermissionProbe(),
                        place: PermissionPlace = .sources, openAtOnce: Bool = false,
                        onFinish: ((Bool) -> Void)? = nil,
                        onGranted: @escaping () -> Void) -> PermissionDragHelperModel {
        current?.model.cancel()
        let model = PermissionDragHelperModel(kind: kind, probe: probe, opener: LivePermissionSettingsOpener(),
                                              clock: LivePermissionPollClock(), place: place,
                                              memory: PermissionMemory(), relauncher: LiveAppRelauncher(),
                                              appName: appName)
        let helper = PermissionDragHelper(model: model)
        current = helper
        model.onGranted = onGranted
        model.onFinish = { [weak helper, weak model] in
            helper?.closePanel()
            if current === helper { current = nil }
            onFinish?(model?.phase == .granted)
        }
        model.onPoll = { [weak helper] in helper?.placeBanner() }
        model.start()
        if !model.isFinished {
            helper.showBanner()
            // Back from System Settings: one look by preflight, and the words move on (toggle, or Reopen).
            helper.activeObserver = NotificationCenter.default.addObserver(
                forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak helper] _ in
                MainActor.assumeIsolated { helper?.returned() }
            }
            if openAtOnce { helper.openSettings() }
        }
        return model
    }

    private func returned() {
        model.returned()
        fitBanner()
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
        // Not movable by its background (the default): a drag on the icon is the app's drag.
        return panel
    }

    private func showBanner() {
        let panel = Self.makePanel()
        let host = NSHostingView(rootView: PermissionBanner(
            model: model, appURL: Bundle.main.bundleURL, icon: NSWorkspace.shared.icon(forFile: Bundle.main.bundlePath),
            onOpen: { [weak self] in self?.openSettings() },
            onReopen: { [weak self] in self?.model.reopen() }))
        panel.contentView = host
        panel.setContentSize(host.fittingSize)
        self.panel = panel
        placeBanner()
        panel.orderFrontRegardless()
    }

    /// Open: the exact list in System Settings, and the banner over it.
    private func openSettings() {
        model.open()
        fitBanner()
        // System Settings takes a moment to open its window: place the banner again once it has.
        DispatchQueue.main.asyncAfter(deadline: .now() + CicadaTiming.permissionPoll) { [weak self] in
            self?.placeBanner()
        }
    }

    /// The banner's words and action change with its state: it fits them, then finds its place again.
    private func fitBanner() {
        guard let panel, let host = panel.contentView else { return }
        panel.setContentSize(host.fittingSize)
        placeBanner()
    }

    /// Centred under System Settings' window, beside the list the icon is dragged into — inside its lower edge when the
    /// screen has no room below. Before System Settings shows, at the top of the screen. Window bounds only — no title,
    /// no permission.
    private func placeBanner() {
        guard let panel else { return }
        let size = panel.frame.size
        let visible = NSScreen.main?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 876)
        guard let settings = Self.systemSettingsFrame() else {
            panel.setFrameOrigin(CGPoint(x: visible.midX - size.width / 2, y: visible.maxY - size.height))
            return
        }
        let x = min(max(settings.midX - size.width / 2, visible.minX), visible.maxX - size.width)
        let below = settings.minY - size.height
        panel.setFrameOrigin(CGPoint(x: x, y: below >= visible.minY ? below : settings.minY))
    }

    private func closePanel() {
        if let activeObserver { NotificationCenter.default.removeObserver(activeObserver) }
        activeObserver = nil
        panel?.orderOut(nil)
        panel = nil
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

// MARK: - The banner

/// What the banner's one action is, by state (owner 2026-11-03: at most one small action). Pure; tested.
enum PermissionBannerAction: Equatable {
    /// Not opened yet (a host that did not open at once, a relaunch's resume): the one primary, Open.
    case open
    /// Opened, a kind whose grant may wait for a fresh process: "Already on? Reopen Cicada", quietly.
    case alreadyOn
    /// Back with no grant on such a kind: Reopen Cicada is the one primary.
    case reopen
    /// Opened, nothing else to offer: the icon is the action.
    case none

    @MainActor static func of(_ model: PermissionDragHelperModel) -> PermissionBannerAction {
        if model.ask == .reopen { return .reopen }
        if model.phase == .asking { return .open }
        return model.offersReopen ? .alreadyOn : .none
    }
}

/// The one banner: the app's icon (the drag source, hopping as it arrives), one line, at most one action, and ×.
private struct PermissionBanner: View {
    let model: PermissionDragHelperModel
    let appURL: URL
    let icon: NSImage
    let onOpen: () -> Void
    let onReopen: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var lift: CGFloat = 0

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            Image(nsImage: icon)
                .resizable()
                .frame(width: CicadaTheme.scaled(48), height: CicadaTheme.scaled(48))
                .overlay(AppTileDragSource(url: appURL))
                .offset(y: lift)
                .help(Copy.Traces.dragHint)
                .accessibilityLabel(Copy.Traces.dragHint)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(model.need)
                    .font(CicadaTheme.rowFont.weight(.semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                action
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            IconButton(systemName: "xmark", help: Copy.Traces.closeHelper, accessibilityLabel: Copy.Traces.closeHelper) {
                model.cancel()
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(420), alignment: .leading)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .padding(CicadaTheme.spacingXL)   // room for the light theme's one soft shadow inside the clear window
        .onAppear { hop(CicadaMotion.helperBounceHops) }
        .onChange(of: model.phase) { _, now in if now == .opened { hop(CicadaMotion.helperBounceHops) } }
    }

    @ViewBuilder
    private var action: some View {
        switch PermissionBannerAction.of(model) {
        case .open:
            PrimaryActionButton(title: Copy.Traces.open, action: onOpen)
                .help(Copy.Traces.openHelp)
        case .alreadyOn:
            TextButton(title: Copy.Permission.alreadyOn(model.appName), flushLeading: true, action: onReopen)
                .help(Copy.Permission.reopenHelp)
        case .reopen:
            PrimaryActionButton(title: Copy.Permission.reopen(model.appName), action: onReopen)
                .help(Copy.Permission.reopenHelp)
        case .none:
            EmptyView()
        }
    }

    /// The arrival hop: a quick rise and a springy landing, `hops` times; nothing under Reduce Motion (DR-66).
    private func hop(_ hops: Int) {
        guard hops > 0, let up = CicadaMotion.helperBounce(up: true, reduceMotion: reduceMotion),
              let down = CicadaMotion.helperBounce(up: false, reduceMotion: reduceMotion) else { return }
        withAnimation(up, completionCriteria: .logicallyComplete) {
            lift = -CicadaMotion.helperBounceRise
        } completion: {
            withAnimation(down, completionCriteria: .logicallyComplete) { lift = 0 } completion: { hop(hops - 1) }
        }
    }
}

/// A host row's button for one permission, through the one helper: its own title until the helper shows, an *Open*
/// link once the person closed the helper (`PermissionRowState.retry`), and nothing once granted (the host shows its
/// own Allowed / On). Traces' steps and switches and the Full Disk Access fix under Messages and a browser use it.
struct PermissionAllowButton: View {
    let kind: TracePermission
    let title: String
    var probe: any TracePermissionProbe = LiveTracePermissionProbe()
    var place: PermissionPlace = .sources
    let onGranted: () -> Void

    @State private var phase: PermissionDragHelperModel.Phase?

    var body: some View {
        switch PermissionRowState.after(phase, granted: false) {
        case .ask:
            NeutralButton(title: title, size: .compact) { present() }
        case .retry:
            TextButton(title: Copy.Traces.open, inline: true) { present() }
                .help(Copy.Permission.retryHelp)
        case .granted:
            EmptyView()
        }
    }

    private func present() {
        phase = .asking
        PermissionDragHelper.present(kind: kind, probe: probe, place: place,
                                     onFinish: { granted in phase = granted ? .granted : .cancelled },
                                     onGranted: onGranted)
    }
}

/// The icon's drag: the app bundle as a file URL, the way Finder drags an app — what System Settings' lists accept.
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
