import SwiftUI

/// Settings → General (G130 R8, re-laid for G139): Appearance (now with
/// System, R-O4), Text size (a direct binding onto `CicadaTheme.uiScale`, so
/// the slider and ⌘+/⌘−/⌘0 stay in lockstep — the setter clamps and is
/// idempotent) and Run setup again (G117: clears the active bank's
/// `OnboardingState` first, then asks the main window for the sheet).
///
/// Appearance writes the same `cicada.colorScheme` key the sidebar's sun/moon
/// toggle already writes, so the two never disagree; `"system"` is the one new
/// value, and `ThemeStore` resolves it against the Mac's own appearance.
///
/// Scene (round-4 D4, G144) retired with the painted art (owner 2026-10-16): it picked a painting, and none is left.
///
/// F-10 (round-4 T-Home, R-HO16) groups the page as *Look* (Appearance · Text size), *Startup* (Open Cicada at
/// login · Show in menu bar) and *When Cicada is closed* (Keep memory working), then *Getting started* (setup, the
/// tour and the demo, one card since the Hyrum audit's B12) and the version. The command-line tool moved to Agents (B11). *Where your memory lives*
/// moved to Devices (settings audit 2026-10-22): one place for where this app's memory is and which devices reach it. Text size stays in Look — F-10 omits it, and removing
/// a working control needs the owner's word. Show in menu bar (`MenuBarPreference`) hides the bookworm without tearing
/// it down; the app keeps its Dock icon, so hiding it never strands Cicada. The rows never promise what the app does not
/// do (R-FA7): the login row says the quiet start R-OB18 built, and 'calendar polls keep going' is not used — the
/// Calendar read is app-side (D2).
///
/// Startup and When Cicada is closed (round-4 D3, G143): Open Cicada at login (`LoginItemService` over `SMAppService.mainApp` —
/// the switch shows the person's intent, the sentence under it macOS's answer, so an unsigned build macOS never
/// enables says so, R-FA7) and Keep memory working (the backend's LaunchAgent: a read-only `launchctl print` probe,
/// and Install runs `scripts/install-backend-agent.sh` only after the click, with the exact command shown first —
/// spec decision 14, R-FA8/R-FA9). The shape follows the macOS login-item pattern (a switch plus an "Open Login
/// Items" link only when approval is pending), with DESIGN_RULES winning: neutral controls (DR-40), the command in
/// a `CommandBox` (DR-19).
struct SettingsGeneralView: View {
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw: String = AppearancePreference.defaultChoice.rawValue
    @AppStorage(MenuBarPreference.defaultsKey) private var showsMenuBar = true
    @Environment(Store.self) private var store
    @Environment(LoginItemService.self) private var loginItems
    @Environment(BackendAgentService.self) private var backendAgent
    /// G182 phase 5 — the in-app updater; inert (and its row hidden) in a developer build.
    @Environment(UpdateService.self) private var updates
    @Environment(AppRouter.self) private var router
    /// G182 — `/healthz`'s version, read once per visit; nil until it answers (never a mismatch).
    @State private var backendVersion: String?
    private let appVersion = AppVersion.current()

    private var appearance: Binding<AppearancePreference> {
        Binding(get: { AppearancePreference.stored(appearanceRaw) }, set: { appearanceRaw = $0.rawValue })
    }

    /// A direct `Binding` onto `CicadaTheme.uiScale` — not a locally-drafted
    /// `@State` mirror — so dragging this slider AND choosing ⌘+/⌘−/⌘0 from
    /// the View menu while Settings is open stay in lockstep: reading
    /// `CicadaTheme.uiScale` in `get` subscribes this view's body to the same
    /// `@Observable` store every other token reads (R2's mechanism). The
    /// setter already clamps/steps (R1) and is idempotent (R4).
    private var scale: Binding<Double> {
        Binding(get: { CicadaTheme.uiScale }, set: { CicadaTheme.uiScale = $0 })
    }

    /// Round 1 (ROR-118): one lead (Appearance, three larger tiles, Text size under them), one card of switches
    /// (login, menu bar, connect suggestions, the background service, the updater), one strip of setup tiles and a
    /// quiet footer. Five blocks and no clipped Version row, where eight cards ran off the panel.
    var body: some View {
        SettingsPage(section: .general) {
            // F-10 — Look: the window's light and the chrome's size.
            SettingsGroupCard {
                // Owner 2026-10-26 — three live miniatures (Light · Dark · System), System by default; the sidebar's
                // toggle retired into this row. Its one-line sentence retired with round 1: the tiles say it.
                SettingsRow(.appearance, title: Copy.appearance) {
                    EmptyView()
                } below: {
                    AppearancePicker(selection: appearance)
                        .padding(.top, CicadaTheme.scaled(2))
                }
                SettingsDivider()
                SettingsRow(.textSize, title: Copy.textSize) {
                    // Round 4 (ROR-118): the readout ends on the card's trailing edge, like every switch below it;
                    // "Actual size" (only while the size is not 100%) sits in the free space to the slider's left,
                    // so it never moves the slider under the pointer.
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text("A")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .accessibilityHidden(true)
                        Slider(value: scale, in: ThemeStore.scaleRange, step: ThemeStore.scaleStep)
                            .frame(width: CicadaTheme.scaled(180))
                        Text("A")
                            .font(CicadaTheme.font(size: 19, weight: .medium))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .accessibilityHidden(true)
                        Text("\(Int((CicadaTheme.uiScale * 100).rounded()))%")
                            .font(CicadaTheme.rowFont.monospacedDigit())
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .frame(width: CicadaTheme.scaled(48), alignment: .trailing)
                    }
                    .overlay(alignment: .leading) {
                        if CicadaTheme.uiScale != 1.0 {
                            NeutralButton(title: Copy.actualSize, size: .compact) { CicadaTheme.resetZoom() }
                                .fixedSize()
                                .alignmentGuide(.leading) { $0[.trailing] + CicadaTheme.spacingMD }
                        }
                    }
                }
            }
            // F-10 — Startup: onboarding's F-06 switches, reversible here (decision 6); with G231's connect
            // suggestion, G143's background service and G182's updater in the same card (round 1: one list of switches).
            SettingsGroupCard {
                // D6 word budget: the state's sentence only when macOS needs the person's approval.
                SettingsRow(.openAtLogin, title: Copy.openAtLogin, detail: loginItems.state.offersSettings
                    ? loginItems.state.detail(menuBarVisible: showsMenuBar) : nil) {
                    Toggle(Copy.openAtLogin, isOn: Binding(get: { loginItems.requested },
                                                           set: { loginItems.setEnabled($0) }))
                        .toggleStyle(.switch)
                        .labelsHidden()
                } below: {
                    if loginItems.state.offersSettings {
                        TextButton(title: Copy.openLoginItems, help: Copy.openLoginItemsHelp) { loginItems.openSystemSettings() }
                    }
                }
                SettingsDivider()
                SettingsRow(.showInMenuBar, title: Copy.showInMenuBar) {
                    Toggle(Copy.showInMenuBar, isOn: $showsMenuBar)
                        .toggleStyle(.switch)
                        .labelsHidden()
                }
                // G231 — the notch's connect suggestion, and the apps the person said No to.
                ConnectSuggestSettingRow()
                SettingsDivider()
                // G181 phase 3 — on a server nothing runs on this Mac for the memory, so nothing is offered.
                let onServer = ServerConnection.current.isServer
                SettingsRow(.backgroundService, title: Copy.keepMemoryWorking,
                            detail: onServer ? Copy.Devices.backgroundNotNeeded
                                : (backendAgent.state == .running ? nil : Copy.backgroundDetail(backendAgent.state))) {
                    if onServer {
                        SettingsInlineLink(section: .devices, row: .memoryHome, label: Copy.Devices.whereGroup)
                    } else {
                        BackgroundServiceButton()
                    }
                } below: {
                    if !onServer && BackgroundServiceButton.showsCommand(backendAgent.state) {
                        CommandBox(command: backendAgent.display)
                    }
                }
                // G182 phase 5 — the updater's switch and its one status line (DR-37: a line never gets a card of its
                // own). Hidden entirely where the updater is inert (a developer build).
                if updates.isActive {
                    SettingsDivider()
                    SettingsRow(.autoUpdate, title: Copy.Updates.autoTitle) {
                        Toggle(Copy.Updates.autoTitle, isOn: Binding(get: { updates.automatic },
                                                                     set: { updates.automatic = $0 }))
                            .toggleStyle(.switch)
                            .labelsHidden()
                    } below: {
                        if updates.state != .idle { UpdateStatusLine() }
                    }
                }
            }
            .task { loginItems.refresh(); await backendAgent.refresh() }
            // The person may have just used System Settings → Login Items (R-FA7).
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                loginItems.refresh()
            }
            // Hyrum audit B12: setup, the tour and the demo are one job, so one strip. The command-line tool left for
            // Agents (B11).
            SettingsDemoTourGroup()
            // G182 — the version a tester reports; the backend's only when it differs (an updated app beside a
            // background service still running the old one). Plain text, monospaced digits (DR-21). An update that
            // couldn't be installed while Cicada was closed is said here, once, for this session (phase 5). Round 1:
            // a footer, not a card — the version beside Report a problem, whose sentence is its tooltip.
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingMD) {
                    Text(Copy.versionLine(appVersion))
                        .font(CicadaTheme.metaFont.monospacedDigit())
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .textSelection(.enabled)
                        .settingsRow(.appVersion)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    // Tester readiness (2026-10-26) — beside the version a report quotes; the same sheet as Help's item.
                    // Round 4 (ROR-118): the quietest control on the page, a text button on the footer line.
                    TextButton(title: Copy.ReportProblem.settingsButton, help: Copy.ReportProblem.settingsDetail) {
                        router.openReportProblem()
                    }
                    .settingsRow(.reportProblem)
                }
                if let note = updates.lastInstallFailure.map({ Copy.Updates.installFailed($0, current: appVersion.short) })
                    ?? (appVersion.differs(fromBackend: backendVersion)
                        ? Copy.versionDetail(appVersion, backend: backendVersion) : nil) {
                    Text(note)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.leading, CicadaTheme.spacingMD)
            .padding(.trailing, max(0, CicadaTheme.spacingMD - TextButton.inset(inline: false)))
            .task(id: store.isConnected) {
                if let health = try? await APIClient.shared.fetchHealth() { backendVersion = health.version }
            }
        }
    }
}

/// R-OB14 — *Keep memory working when Cicada is closed*: one control in Settings → General and onboarding's F-06,
/// so the two can never disagree about what the click does. Install runs only after the click, with the command
/// shown first beside it (spec decision 14, R-FA8/R-FA9, DR-19), and waits while Sleep reads (finding 6, DR-41).
struct BackgroundServiceButton: View {
    @Environment(BackendAgentService.self) private var backendAgent
    @Environment(Store.self) private var store

    /// The command shows before the click, beside the button (`CommandBox`, DR-19) — only while Install is offered.
    static func showsCommand(_ state: BackendAgentState) -> Bool {
        switch state {
        case .missing, .stopped, .failed: true
        default: false
        }
    }

    /// A native switch's height, so a row with a word in its place stands as tall as its neighbours.
    private static let switchHeight: CGFloat = 28
    /// The switch's track ends a little inside its frame; the word ends on the track's edge.
    private static let switchTrailingInset: CGFloat = 2

    var body: some View {
        switch backendAgent.state {
        case .missing, .stopped, .failed:
            // Finding 6 (DR-41) — installing stops the app's own backend once launchd has the port, which would kill
            // a running cycle mid-stage and leave its pages for the next `git add -A` writer (the G85 smear). The whole
            // run, not only its write window (G177): a stopped backend ends a drain between its batches too.
            let sleeping = ProjectWriteGate.sleepRunning(store.status.value)
            NeutralButton(title: Copy.backgroundInstall, size: .compact, isDisabled: sleeping,
                          help: Copy.backgroundInstallHelp, disabledHelp: Copy.backgroundWaitForSleep) {
                guard !ProjectWriteGate.sleepRunning(store.status.value) else { return }
                Task { await backendAgent.install() }
            }
        case .unknown:
            NeutralButton(title: Copy.foundRetry, size: .compact) { Task { await backendAgent.refresh() } }
        case .checking, .installing:
            ProgressView().controlSize(.small)
        case .running:
            // Round 4 (ROR-118): it has no off switch here (the service is installed, not toggled), so it is a plain
            // word where the switches sit, at their height and on their trailing edge. The green dot, a pattern no
            // other row had, is gone.
            Text(Copy.Status.on)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(minHeight: CicadaTheme.scaled(Self.switchHeight))
                .padding(.trailing, CicadaTheme.scaled(Self.switchTrailingInset))
                .fixedSize()
        }
    }
}

/// G182 phase 5 — the line under *Install updates automatically*: where the updater stands, in words, recomputed each
/// minute so "checked 2 hours ago" is true when read (DR-58); digits stay tabular (DR-21). Its actions are the house
/// buttons (DR-40): *What's new* and *Download* are text buttons, *Restart to update* a neutral one — disabled, with
/// the reason in `.help`, while Sleep writes (DR-41), because installing restarts the background service.
struct UpdateStatusLine: View {
    @Environment(UpdateService.self) private var updates
    @Environment(Store.self) private var store

    var body: some View {
        TimelineView(.everyMinute) { context in
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                if let line = Copy.Updates.statusLine(updates.state, now: context.date,
                                                      deferredVersion: updates.deferredVersion,
                                                      sleepRefused: mustInsist) {
                    Text(line)
                        .font(CicadaTheme.captionFont.monospacedDigit())
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                actions
            }
        }
    }

    @ViewBuilder private var actions: some View {
        switch updates.state {
        case .available(let manifest):
            notes(manifest)
            TextButton(title: Copy.Updates.download, help: Copy.Updates.downloadHelp(manifest.version)) {
                Task { await updates.download() }
            }
        case .ready(let manifest):
            notes(manifest)
            if mustInsist {
                NeutralButton(title: Copy.Updates.restartAnyway, size: .compact,
                              help: Copy.Updates.restartHelp(manifest.version)) { updates.restartAnyway() }
            } else {
                NeutralButton(title: Copy.Updates.restart, size: .compact, help: Copy.Updates.restartHelp(manifest.version)) {
                    Task { await updates.restartToUpdate() }
                }
            }
        case .checking, .downloading, .installing:
            ProgressView().controlSize(.small)
        default:
            EmptyView()
        }
    }

    /// Sleep is reading, or the backend wouldn't say: the line names what a restart costs, and the button goes ahead.
    private var mustInsist: Bool { updates.sleepRefusedRestart || ProjectWriteGate.sleepRunning(store.status.value) }

    /// The release notes, only from a secure address the manifest named; opened in the person's browser on their click.
    @ViewBuilder private func notes(_ manifest: UpdateManifest) -> some View {
        if let url = manifest.notesURL, url.scheme == "https" {
            TextButton(title: Copy.Updates.whatsNew, help: Copy.Updates.whatsNewHelp) { NSWorkspace.shared.open(url) }
        }
    }
}
