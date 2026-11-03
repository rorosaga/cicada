import AppKit
import SwiftUI

/// The rows' live state: every shown permission's preflight, looked at again while the rows show, when Cicada becomes
/// active, and right after a row's own ask. Nothing here asks on its own (`MacPermissionProbe` never prompts).
@MainActor
@Observable
final class PermissionListModel {
    private(set) var states: [MacPermission: MacPermissionState] = [:]
    /// The rows the person clicked in this showing: only these mark a grant (the sound, the helper's close).
    private(set) var asked: Set<MacPermission> = []
    /// A row whose ask is in flight (its button waits).
    private(set) var asking: MacPermission?

    @ObservationIgnored private let probe: any MacPermissionProbe
    @ObservationIgnored private let asker: any MacPermissionAsker
    @ObservationIgnored var onGranted: ((MacPermission) -> Void)?

    init(probe: any MacPermissionProbe = LiveMacPermissionProbe(),
         asker: any MacPermissionAsker = LiveMacPermissionAsker()) {
        self.probe = probe
        self.asker = asker
    }

    func refresh(_ permissions: [MacPermission]) async {
        var next = states
        for permission in permissions { next[permission] = await probe.state(permission) }
        let landed = MacPermissionRows.newlyGranted(before: states, after: next, asked: asked)
        states = next
        for permission in landed.sorted(by: { $0.rawValue < $1.rawValue }) { onGranted?(permission) }
    }

    /// A prompt-kind row's button: macOS's own prompt (Automation opens its app in the background first), then a look.
    func ask(_ permission: MacPermission) async {
        guard asking == nil else { return }
        asked.insert(permission)
        asking = permission
        await asker.ask(permission)
        asking = nil
        await refresh([permission])
    }

    /// A drag row's button or a refused row's: the person is about to act in System Settings.
    func noteAsked(_ permission: MacPermission) { asked.insert(permission) }
}

/// The Permissions rows, one per permission (onboarding's step and Settings → Privacy & data, the same component):
/// the app's own icon or a glyph, the name, what it unlocks in one line, and either a green dot with *Allowed* or the
/// one button that does the right thing for that kind — the drag helper over the exact list for Full Disk Access,
/// Accessibility and Screen Recording (opened at once, `PermissionDragHelper.present(openAtOnce:)`), macOS's own prompt
/// for Contacts, Calendars, Reminders, Notifications and Automation, and the exact list once a prompt was refused. Every
/// row can stay as it is: nothing is required, and Continue never waits on one. DR-5 (the buttons are neutral; the
/// step's one primary stays its foot's Continue), DR-9/DR-10 (the card is a ring, not a shadow), DR-12, DR-39, DR-52
/// (an installed app's own icon), DR-59; no motion of its own (DR-60, DR-66).
struct PermissionList: View {
    let permissions: [MacPermission]
    /// Where a relaunch the drag helper needs brings the person back.
    let place: PermissionPlace
    var onGranted: ((MacPermission) -> Void)?
    @State private var model: PermissionListModel

    init(permissions: [MacPermission], place: PermissionPlace, onGranted: ((MacPermission) -> Void)? = nil,
         model: PermissionListModel? = nil) {
        self.permissions = permissions
        self.place = place
        self.onGranted = onGranted
        _model = State(initialValue: model ?? PermissionListModel())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(permissions.enumerated()), id: \.element) { index, permission in
                if index > 0 { SettingsDivider() }
                row(permission)
            }
        }
        .task(id: permissions) {
            model.onGranted = onGranted
            while !Task.isCancelled {
                await model.refresh(permissions)
                try? await Task.sleep(for: .seconds(CicadaTiming.permissionRowsPoll))
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await model.refresh(permissions) }
        }
    }

    private func row(_ permission: MacPermission) -> some View {
        let state = model.states[permission]
        let granted = state == .granted
        return ConnectionLine(logo: nil, name: Copy.MacPermissions.name(permission), bundleId: permission.appBundleId,
                              systemFallback: permission.glyph, detail: Copy.MacPermissions.unlocks(permission),
                              status: granted ? (Copy.MacPermissions.allowed, true) : nil, detailLines: 1) {
            control(permission, state: state)
        }
    }

    @ViewBuilder
    private func control(_ permission: MacPermission, state: MacPermissionState?) -> some View {
        // Unknown until the first look: no button yet, so nothing is offered that may already be done.
        if state != nil {
            switch MacPermissionRows.action(permission, state: state) {
            case .none:
                EmptyView()
            case .drag(let kind):
                NeutralButton(title: Copy.MacPermissions.allow, size: .compact) {
                    model.noteAsked(permission)
                    PermissionDragHelper.present(kind: kind, place: place, openAtOnce: true) {
                        Task { await model.refresh([permission]) }
                    }
                }
                .help(Copy.MacPermissions.allowHelp)
            case .ask:
                NeutralButton(title: Copy.MacPermissions.allow, size: .compact) {
                    Task { await model.ask(permission) }
                }
                .disabled(model.asking != nil)
                .help(Copy.MacPermissions.askHelp)
            case .openSettings:
                NeutralButton(title: Copy.MacPermissions.openSetting, size: .compact) {
                    model.noteAsked(permission)
                    NSWorkspace.shared.open(permission.settingsURL())
                }
                .help(Copy.MacPermissions.openSettingHelp)
            }
        }
    }
}

/// The rows this Mac shows, on their card: Chrome's only when it is installed, traces' two only while traces are on
/// (`MacPermissionRows.visible`). Onboarding's Permissions step and Settings → Privacy & data both draw this.
struct MacPermissionsCard: View {
    let place: PermissionPlace
    var onGranted: ((MacPermission) -> Void)?

    @Environment(TraceRecorder.self) private var traces: TraceRecorder?

    private var permissions: [MacPermission] {
        let chrome = NSWorkspace.shared.urlForApplication(withBundleIdentifier: MacPermission.chromeBundleId) != nil
        return MacPermissionRows.visible(tracesOn: traces?.settings.enabled == true, chromeInstalled: chrome)
    }

    var body: some View {
        PermissionList(permissions: permissions, place: place, onGranted: onGranted)
            .settingsCardSurface()
    }
}

/// The same rows inside a Settings card that already draws the surface (Settings → Privacy & data).
struct MacPermissionsRows: View {
    let place: PermissionPlace

    @Environment(TraceRecorder.self) private var traces: TraceRecorder?

    var body: some View {
        let chrome = NSWorkspace.shared.urlForApplication(withBundleIdentifier: MacPermission.chromeBundleId) != nil
        PermissionList(permissions: MacPermissionRows.visible(tracesOn: traces?.settings.enabled == true,
                                                             chromeInstalled: chrome),
                       place: place)
    }
}
