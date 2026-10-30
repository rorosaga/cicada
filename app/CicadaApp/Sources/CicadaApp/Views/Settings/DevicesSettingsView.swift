import SwiftUI

/// G181 phase 3 — Settings → Devices' *Where your memory lives* (on General until the settings audit, 2026-10-22):
/// This Mac or A server (address + this device's token).
///
/// A change is checked against the server before anything is written (`ServerProbe`: `/healthz` says it is Cicada,
/// `/devices` with the token says the token is good and names this device), then saved to `$CICADA_HOME/api_base` and
/// `device_token` (0600) and used when Cicada opens again — the Store, its cache, the event stream and the readers
/// switch together (`ServerConnection`). Choosing This Mac again removes only the address. DR-40: neutral buttons and
/// text buttons; DR-41: Restart waits while Sleep runs (a backend this app spawned would stop with it); DR-19: the
/// commands a person runs on the server are shown as commands.
struct MemoryHomeSetting: View {
    @State private var model = ConnectionSettingsModel()
    @State private var replacingToken = false
    @Environment(Store.self) private var store

    var body: some View {
        // D6 word budget: the choice explains itself on This Mac; only the server form needs its sentence.
        SettingsRow(.memoryHome, title: Copy.Devices.modeTitle,
                    detail: model.choice == .thisMac ? nil : Copy.Devices.serverDetail) {
            PillPicker(title: Copy.Devices.modeTitle, selection: $model.choice,
                       options: ConnectionSettingsModel.Choice.allCases.map { PillOption(value: $0, label: $0.label) })
                .disabled(model.lockedByEnvironment)
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if model.lockedByEnvironment {
                    caption(Copy.Devices.environmentSet)
                    // Settings defaults pass 2 (#405 review): where the pin is undone — the docs page, never the variable.
                    SettingsHelpLink(url: Copy.SettingsHelp.serverFixed)
                        .font(CicadaTheme.captionFont)
                } else if model.choice == .server {
                    serverForm
                } else if model.saved.isServer {
                    NeutralButton(title: Copy.Devices.useThisMac, size: .compact) { model.useThisMac() }
                }
                if let pending = model.pendingLine { restartLine(pending) }
            }
        }
    }

    @ViewBuilder private var serverForm: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.Devices.addressTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            TextField(Copy.Devices.addressPlaceholder, text: $model.address)
                .textFieldStyle(.roundedBorder)
                .font(CicadaTheme.bodyFont)
                .help(Copy.Devices.addressHelp)
        }
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.Devices.tokenTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            if model.tokenSaved && !replacingToken {
                HStack(spacing: CicadaTheme.spacingSM) {
                    caption(Copy.Devices.tokenSaved)
                    TextButton(title: Copy.Devices.tokenReplace, inline: true) { replacingToken = true }
                }
            } else {
                SecureField(Copy.Devices.tokenPlaceholder, text: $model.token)
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.bodyFont)
            }
            caption(Copy.Devices.tokenHelp)
        }
        HStack(spacing: CicadaTheme.spacingSM) {
            NeutralButton(title: Copy.Devices.check, size: .compact,
                          isDisabled: model.checking || model.address.trimmingCharacters(in: .whitespaces).isEmpty) {
                Task {
                    await model.checkAndUse()
                    if case .ok? = model.result { replacingToken = false }
                }
            }
            if model.checking {
                ProgressView().controlSize(.small)
                caption(Copy.Devices.checking)
            }
        }
        if let result = model.result {
            if case .ok(let name) = result {
                caption(Copy.Devices.checkedOK(model.saved.host ?? "", device: name))
            } else {
                Text(result.message)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func restartLine(_ pending: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                caption(pending)
                Spacer(minLength: CicadaTheme.spacingSM)
                if AppRelaunch.canRelaunch {
                    let sleeping = ProjectWriteGate.sleepRunning(store.status.value)
                    NeutralButton(title: Copy.Devices.restart, size: .compact, isDisabled: sleeping,
                                  help: Copy.Devices.restartHelp, disabledHelp: Copy.backgroundWaitForSleep) {
                        guard !ProjectWriteGate.sleepRunning(store.status.value) else { return }
                        AppRelaunch.relaunch()
                    }
                }
            }
            if !AppRelaunch.canRelaunch { caption(Copy.Devices.restartByHand) }
            caption(Copy.Devices.agentsFollow)
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}


/// Settings → Devices (G181 phase 3, G212, ruling 36 D6): each machine by its own name — the server by its Computer
/// Name, never "this Mac" (owner, 2026-10-22) — with a dot and one word, how it connects (this machine, Tailscale,
/// SSH, local network), when it was last seen and how many of its conversations wait for Sleep, and Revoke. *Pair a
/// device* shows a one-time code as a QR drawn here (`PairDeviceSheet`). Where the memory lives (This Mac or a server)
/// and the remote connector (*Apps outside this machine*, folded, DR-39) close the page. `GET /devices/status` is not a
/// Store domain (it changes by the minute): read on appear and every 30 s while the page is open, kept in memory.
struct DevicesSettingsView: View {
    @State private var model = DevicesPageModel(api: APIClient.shared, connection: APIClient.shared.connection,
                                                directory: DeviceDirectory.shared)
    @State private var rows: [DeviceStatusRow] = []
    @State private var pairing = false
    @State private var pendingRevoke: DeviceStatusRow?
    /// The device the pairing sheet just paired, so an older row of the same name can be offered for revoking.
    @State private var justPaired: String?
    @State private var appsOpen = false

    var body: some View {
        SettingsPage(section: .devices) {
            SettingsGroupCard {
                TimelineView(.everyMinute) { context in
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                            if index > 0 { SettingsDivider() }
                            ConnectionLine(logo: nil, name: row.name, systemFallback: Self.symbol(row),
                                           detail: Self.detail(row, now: context.date),
                                           status: (Self.presence(row, now: context.date).word,
                                                    Self.presence(row, now: context.date).on)) {
                                if model.canManage, let id = row.deviceId, !row.current {
                                    TextButton(title: Copy.DevicesPage.revoke, inline: true) { pendingRevoke = row }
                                        .accessibilityIdentifier("devices.revoke.\(id)")
                                }
                            }
                        }
                    }
                }
                if model.canManage, let twin = Self.olderTwins(rows, newDeviceId: justPaired).first {
                    // Review 2026-10-29: the same phone paired again leaves its old row (its old token) behind; offer to
                    // revoke it, behind the same confirmation as any Revoke. An offer only — nothing is revoked here.
                    SettingsDivider()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.DevicesPage.olderTwin(twin.name))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        TextButton(title: Copy.DevicesPage.revokeOlder, inline: true) { pendingRevoke = twin }
                            .accessibilityIdentifier("devices.revokeOlder")
                    }
                    .padding(CicadaTheme.spacingMD)
                }
                if model.canManage {
                    // 2026-10-29: the guided reach step sits right above the button it makes work.
                    SettingsDivider()
                    DeviceReachSection()
                    SettingsDivider()
                    HStack {
                        Spacer()
                        NeutralButton(title: Copy.DevicesPage.pair, systemImage: "qrcode", size: .compact) { pairing = true }
                    }
                    .padding(CicadaTheme.spacingMD)
                }
            }
            .settingsRow(.devicesList)
            SettingsGroupCard {
                MemoryHomeSetting()
                if let line = model.connectionLine {
                    SettingsDivider()
                    SettingsRow(.devicesConnection, title: line, detail: model.connection.invalidReason) {
                        EmptyView()
                    } below: {
                        connectionStatus
                    }
                }
            }
            // G132 phase 1: share this memory with the person's other computers, or keep a full copy of another's here.
            MemoryCopySetting()
            // G132 phase 3b: the relay (off by default) — pair a computer through it, or join one with a code.
            RelaySection(canManage: model.canManage)
            // Hyrum audit B1 / D6: the remote connector, unchanged, folded (DR-39) under the old page's anchor.
            SettingsGroupCard {
                DisclosureGroup(isExpanded: $appsOpen) {
                    RemoteAccessView().padding(.top, CicadaTheme.spacingSM)
                } label: {
                    Text(Copy.DevicesPage.apps)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                }
                .padding(CicadaTheme.spacingMD)
            }
            .settingsRow(.fromAnywhere)
        }
        .task {
            await refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if Task.isCancelled { break }
                await refresh()
            }
        }
        .sheet(isPresented: $pairing) {
            PairDeviceSheet { paired in pairing = false; justPaired = paired; Task { await refresh() } }
        }
        .confirmationDialog(Copy.Devices.revokeTitle(pendingRevoke?.name ?? ""),
                            isPresented: Binding(get: { pendingRevoke != nil }, set: { if !$0 { pendingRevoke = nil } }),
                            titleVisibility: .visible) {
            Button(Copy.Devices.revoke, role: .destructive) {
                if let id = pendingRevoke?.deviceId {
                    Task { _ = try? await APIClient.shared.revokeDevice(id: id); await refresh() }
                }
                pendingRevoke = nil
            }
            Button(Copy.Devices.cancel, role: .cancel) { pendingRevoke = nil }
        } message: {
            Text(Copy.Devices.revokeMessage)
        }
    }

    private func refresh() async {
        await model.refresh()
        if let answer = try? await APIClient.shared.fetchDeviceStatus() {
            rows = answer.devices.map { row in
                var row = row
                // The server names itself by its Computer Name; an older backend's blank name falls back to this
                // machine's own, never to "this Mac".
                if row.name.isEmpty, row.isServer { row.name = Host.current().localizedName ?? row.name }
                return row
            }
        }
    }

    /// The active rows that share the just-paired device's name (case and spaces aside), the new one excluded — the
    /// same phone paired again; never the server row. Empty when nothing was just paired.
    static func olderTwins(_ rows: [DeviceStatusRow], newDeviceId: String?) -> [DeviceStatusRow] {
        guard let newDeviceId, let fresh = rows.first(where: { $0.deviceId == newDeviceId }) else { return [] }
        let key = { (name: String) in name.split(whereSeparator: \.isWhitespace).joined(separator: " ").lowercased() }
        return rows.filter { !$0.isServer && $0.deviceId != nil && $0.deviceId != newDeviceId && key($0.name) == key(fresh.name) }
    }

    static func symbol(_ row: DeviceStatusRow) -> String {
        if row.isServer { return "desktopcomputer" }
        let name = row.name.lowercased()
        if name.contains("iphone") || name.contains("phone") { return "iphone" }
        if name.contains("ipad") { return "ipad" }
        return "laptopcomputer"
    }

    /// The agents' rule (fix round 2026-10-22): the backend's own *connected* (seen within its window) is Connected; a
    /// paired device seen before is Connected too (green; its line says "last seen <day>"); one never seen is Not connected.
    static func presence(_ row: DeviceStatusRow, now: Date) -> Copy.Presence {
        if row.connected { return .connected }
        return row.lastSeenAt != nil ? .idle : .notConnected
    }

    /// "Tailscale · 3 min ago · 2 waiting", or "… · last seen Oct 21" — how, when, and what waits; each part only
    /// when known.
    static func detail(_ row: DeviceStatusRow, now: Date) -> String {
        var parts: [String] = []
        if let how = ConnectionModelText.how(row.how) { parts.append(how) }
        if !row.isServer, let seen = row.lastSeenAt.flatMap(ISODate.parse) {
            parts.append(row.connected ? Copy.AgentsPage.seen(seen, now: now) : Copy.AgentsPage.lastSeen(seen))
        }
        if row.queue > 0 { parts.append(Copy.DevicesPage.waiting(row.queue)) }
        // 2026-10-29: what the device may do and whether its token needs its own key — only when the backend says.
        if !row.isServer {
            switch row.kind {
            case "capture": parts.append(Copy.DevicesPage.captureOnly)
            case "full": parts.append(Copy.DevicesPage.fullAccess)
            default: break
            }
            if let bound = row.keyBound {
                if bound, let since = row.keyBoundAt.flatMap(ISODate.parse) {
                    parts.append(Copy.DevicesPage.keyBoundSince(since))
                } else {
                    parts.append(bound ? Copy.DevicesPage.keyBound : Copy.DevicesPage.notKeyBound)
                }
            }
        }
        return parts.joined(separator: " · ")
    }

    private var connectionStatus: some View {
        TimelineView(.everyMinute) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let line = model.statusLine(at: context.date) {
                    Text(line)
                        .font(CicadaTheme.captionFont.monospacedDigit())
                        .foregroundStyle(model.reachable == false ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                if model.waiting > 0 {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.Devices.waiting(model.waiting))
                            .font(CicadaTheme.captionFont.monospacedDigit())
                            .foregroundStyle(CicadaTheme.textSecondary)
                        TextButton(title: Copy.Devices.sendNow, inline: true) {
                            Task { await model.sendNow() }
                        }
                    }
                }
                if model.waitingElsewhere > 0 {
                    Text(Copy.Devices.waitingElsewhere(model.waitingElsewhere))
                        .font(CicadaTheme.captionFont.monospacedDigit())
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }
}

/// Add a device: a name, then its token, shown once, with the address and the two places it goes on that device.
struct AddDeviceSheet: View {
    let model: DevicesPageModel
    var onClose: () -> Void
    @State private var name = ""
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if let created = model.created {
                Text(Copy.Devices.shownOnceTitle).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(created.device.name).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                CommandBox(command: created.token)
                Text(Copy.Devices.shownOnceDetail)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Spacer()
                    NeutralButton(title: Copy.Devices.done) {
                        model.created = nil
                        onClose()
                    }
                }
            } else {
                Text(Copy.Devices.add).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Devices.nameTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    TextField(Copy.Devices.namePlaceholder, text: $name).textFieldStyle(.roundedBorder)
                }
                if let problem = model.problem {
                    Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    Spacer()
                    TextButton(title: Copy.Devices.cancel) { onClose() }
                    NeutralButton(title: Copy.Devices.create,
                                  isDisabled: busy || name.trimmingCharacters(in: .whitespaces).isEmpty) {
                        busy = true
                        Task {
                            await model.add(name: name)
                            busy = false
                        }
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .background(CicadaTheme.background)
    }
}
