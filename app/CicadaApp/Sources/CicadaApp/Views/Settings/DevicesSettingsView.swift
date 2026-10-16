import SwiftUI

/// G181 phase 3 — Settings → General's *Where your memory lives*: This Mac or A server (address + this device's token).
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
        SettingsRow(.memoryHome, title: Copy.Devices.modeTitle,
                    detail: model.choice == .thisMac ? Copy.Devices.thisMacDetail : Copy.Devices.serverDetail) {
            PillPicker(title: Copy.Devices.modeTitle, selection: $model.choice,
                       options: ConnectionSettingsModel.Choice.allCases.map { PillOption(value: $0, label: $0.label) })
                .disabled(model.lockedByEnvironment)
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if model.lockedByEnvironment {
                    caption(Copy.Devices.environmentSet)
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

/// G181 phase 3 — Settings → Devices (owner 2026-10-16: "a page in settings … where I can see the synced devices").
///
/// Two cards: *This app* — where this app's memory lives, whether the server answers and as of when, and how many
/// captures wait on this Mac for it — and *Your devices*: each device the person issued a token for, when it was added
/// and last seen, Revoke. On This Mac (the master token) the page adds a device, showing its token once, and revokes
/// one; on a server's client it reads the list and says the two commands to run on the server (ruling 28.1). Not a
/// Store domain (`/devices` is outside every bank): read on appear and every 30 s while the page is open, kept in
/// memory. DR-40 controls, DR-58 "ago" recomputed each minute, DR-21 tabular digits.
struct DevicesSettingsView: View {
    @State private var model = DevicesPageModel(api: APIClient.shared, connection: APIClient.shared.connection,
                                                directory: DeviceDirectory.shared)
    @State private var showAdd = false
    @State private var pendingRevoke: DeviceRecord?

    var body: some View {
        SettingsPage(section: .devices) {
            SettingsGroupCard(header: Copy.Devices.connectionGroup) {
                SettingsRow(.devicesConnection, title: model.connectionLine,
                            detail: model.connection.invalidReason) {
                    EmptyView()
                } below: {
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
                        }
                    }
                }
            }
            SettingsGroupCard(header: Copy.Devices.devicesGroup) {
                SettingsRow(.devicesList, title: Copy.Devices.devicesGroup,
                            detail: model.canManage ? nil : Copy.Devices.addOnServer) {
                    if model.canManage {
                        NeutralButton(title: Copy.Devices.add, size: .compact, help: Copy.Devices.addHelp) {
                            showAdd = true
                        }
                    }
                } below: {
                    deviceList
                }
            }
        }
        .task {
            await model.refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if Task.isCancelled { break }
                await model.refresh()
            }
        }
        .sheet(isPresented: $showAdd) {
            AddDeviceSheet(model: model) { showAdd = false }
        }
        .confirmationDialog(Copy.Devices.revokeTitle(pendingRevoke?.name ?? ""),
                            isPresented: Binding(get: { pendingRevoke != nil }, set: { if !$0 { pendingRevoke = nil } }),
                            titleVisibility: .visible) {
            Button(Copy.Devices.revoke, role: .destructive) {
                if let target = pendingRevoke { Task { await model.revoke(target) } }
                pendingRevoke = nil
            }
            Button(Copy.Devices.cancel, role: .cancel) { pendingRevoke = nil }
        } message: {
            Text(Copy.Devices.revokeMessage)
        }
    }

    @ViewBuilder private var deviceList: some View {
        TimelineView(.everyMinute) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if model.loadFailed && model.devices.isEmpty {
                    Text(Copy.Devices.loadFailed).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                } else if model.devices.isEmpty {
                    Text(Copy.Devices.none).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(model.devices) { device in
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "laptopcomputer")
                            .font(CicadaTheme.font(size: 12))
                            .foregroundStyle(CicadaTheme.textTertiary)
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            HStack(spacing: CicadaTheme.spacingXS) {
                                Text(device.name)
                                    .font(CicadaTheme.font(size: 13, weight: .medium))
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                if device.current {
                                    Text(Copy.Devices.thisDevice)
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                            }
                            Text(model.detail(device, at: context.date))
                                .font(CicadaTheme.captionFont.monospacedDigit())
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if model.canManage && device.active {
                            TextButton(title: Copy.Devices.revoke, inline: true) { pendingRevoke = device }
                        }
                    }
                    .opacity(device.active ? 1 : 0.6)
                }
                if let problem = model.problem {
                    Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
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
