import SwiftUI

/// Settings → Agents → "From anywhere" (G135, R-R7).
///
/// Three cards, in the order a person sets this up: the master switch (off by
/// default — nothing listens until it is on), how apps reach this Mac (Cicada
/// detects Tailscale or ngrok and shows the one command; it never opens a
/// tunnel itself, G132 (c)), and the connectors. A token is shown once, in
/// the New connector sheet or after a Rotate; nothing on this page can show it
/// again. Not a sync domain (R-R33): it fetches on appear, after every change,
/// and every 30 s while the switch is on.
struct RemoteAccessView: View {
    @State private var status: RemoteStatus?
    @State private var connectors: [RemoteConnector] = []
    @State private var problem: String?
    @State private var switching = false
    @State private var customURL = ""
    @State private var showCustomURL = false
    @State private var showNewConnector = false
    @State private var rotated: RemoteConnectorCreated?
    @State private var pendingRevoke: RemoteConnector?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                switchCard
                if status?.enabled == true {
                    reachCard
                    connectorsCard
                }
                if let problem {
                    Text(problem)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.danger)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXXL)
        }
        .task { await refresh(probe: true) }
        .task(id: status?.enabled ?? false) { await pollWhileOn() }
        .sheet(isPresented: $showNewConnector) {
            NewConnectorSheet {
                showNewConnector = false
                Task { await refreshConnectors() }
            }
        }
        .sheet(item: $rotated) { created in
            ShownOnceView(created: created) { rotated = nil }
                .frame(width: CicadaTheme.scaled(560), height: CicadaTheme.scaled(600))
                .background(CicadaTheme.background)
        }
        .confirmationDialog(
            "Revoke \(pendingRevoke?.label ?? "this connector")?",
            isPresented: Binding(get: { pendingRevoke != nil }, set: { if !$0 { pendingRevoke = nil } }),
            titleVisibility: .visible
        ) {
            Button("Revoke", role: .destructive) {
                if let target = pendingRevoke { Task { await revoke(target) } }
                pendingRevoke = nil
            }
            Button("Cancel", role: .cancel) { pendingRevoke = nil }
        } message: {
            Text("Apps using it stop reaching your memory right away. What they already saved stays, with its source.")
        }
    }

    // MARK: Cards

    private var switchCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "globe")
                .font(CicadaTheme.font(size: 18))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.remoteSwitchTitle)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.remoteSwitchDetail)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Toggle("", isOn: Binding(get: { status?.enabled ?? false },
                                     set: { on in Task { await setEnabled(on) } }))
                .toggleStyle(.switch)
                .labelsHidden()
                .disabled(status == nil || switching)
                .accessibilityLabel(Copy.remoteSwitchTitle)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var reachCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("How apps reach this Mac")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            if let status { reachBody(RemoteReach.of(status), status: status) }
            Text(Copy.remoteNeverOpensTunnel)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            DisclosureGroup(isExpanded: $showCustomURL) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextField("https://…", text: $customURL)
                        .textFieldStyle(.roundedBorder)
                        .font(CicadaTheme.monoFont)
                    Button("Save") { Task { await saveCustomURL(customURL) } }
                        .disabled(customURL.trimmingCharacters(in: .whitespaces).isEmpty)
                    if status?.publicBaseUrl != nil {
                        Button("Clear") { Task { await saveCustomURL("") } }
                    }
                }
                .padding(.top, CicadaTheme.spacingXS)
            } label: {
                Text("I have my own HTTPS address")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    @ViewBuilder
    private func reachBody(_ reach: RemoteReach, status: RemoteStatus) -> some View {
        switch reach {
        case .off:
            EmptyView()
        case .problem(let text):
            line(text, symbol: "exclamationmark.triangle.fill", tint: CicadaTheme.danger)
        case .reachable(let url):
            line("Reachable at \(url)", symbol: "checkmark.circle.fill", tint: CicadaTheme.success)
        case .checking(let url):
            line("Checking \(url)…", symbol: "clock", tint: CicadaTheme.textTertiary)
        case .unreachable(let url):
            line("\(url) didn't answer. Check that the tunnel points at port \(status.port) and this Mac is online.",
                 symbol: "exclamationmark.circle.fill", tint: CicadaTheme.warning)
            checkAgain
        case .setUp(let message, let command):
            Text(message)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let command { CommandBox(command: command) }
            if status.tailscale != "missing" {
                Text(Copy.remoteMachineNameWarning)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.warning)
                    .fixedSize(horizontal: false, vertical: true)
            } else if command == nil, let download = URL(string: "https://tailscale.com/download") {
                Link("Get Tailscale", destination: download)
                    .font(CicadaTheme.bodyFont)
            }
            checkAgain
        }
    }

    private var checkAgain: some View {
        Button("Check again") { Task { await refresh(probe: true) } }
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.accent)
    }

    private func line(_ text: String, symbol: String, tint: Color) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: symbol).foregroundStyle(tint)
            Text(text)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    private var connectorsCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack {
                Text("Connectors")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                Button { showNewConnector = true } label: { Label("New connector", systemImage: "plus") }
                    .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .disabled(status?.effectiveUrl == nil)
            }
            if status?.effectiveUrl == nil {
                Text("First give apps a way to reach this Mac, above.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            let active = connectors.filter(\.isActive)
            let past = connectors.filter { !$0.isActive }
            if active.isEmpty {
                Text("No connectors yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(active) { connector in
                RemoteConnectorRow(connector: connector,
                                   onRotate: { Task { await rotate(connector) } },
                                   onRevoke: { pendingRevoke = connector })
            }
            if !past.isEmpty {
                DisclosureGroup("Past connectors (\(UsageFormat.count(past.count)))") {
                    ForEach(past) { connector in RemoteConnectorRow(connector: connector) }
                }
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(RemoteScope.summary(RemoteScope.defaults))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    // MARK: Actions

    private func refresh(probe: Bool) async {
        do {
            let fresh = try await APIClient.shared.fetchRemoteStatus(probe: probe)
            var merged = fresh
            // A plain poll must not flip a known answer back to "Checking…".
            if !probe, fresh.reachable == nil, let old = status, old.effectiveUrl == fresh.effectiveUrl {
                merged.reachable = old.reachable
            }
            status = merged
            if customURL.isEmpty, let own = merged.publicBaseUrl { customURL = own }
            problem = nil
        } catch {
            problem = "Couldn't reach Cicada's backend. Is it running?"
        }
        await refreshConnectors()
    }

    private func refreshConnectors() async {
        if let list = try? await APIClient.shared.fetchRemoteConnectors() { connectors = list }
    }

    private func pollWhileOn() async {
        guard status?.enabled == true else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(30))
            if Task.isCancelled { return }
            await refresh(probe: false)
        }
    }

    private func setEnabled(_ on: Bool) async {
        switching = true
        defer { switching = false }
        do {
            status = try await APIClient.shared.updateRemoteSettings(enabled: on)
            if on { await refresh(probe: true) }
        } catch {
            problem = "Couldn't change that: \(error.localizedDescription)"
        }
    }

    private func saveCustomURL(_ value: String) async {
        do {
            status = try await APIClient.shared.updateRemoteSettings(publicBaseURL: value.trimmingCharacters(in: .whitespaces))
            await refresh(probe: true)
        } catch {
            problem = "That address didn't work. Use the https:// address your tunnel gave you, with nothing after the host."
        }
    }

    private func rotate(_ connector: RemoteConnector) async {
        do {
            rotated = try await APIClient.shared.rotateRemoteConnector(id: connector.id)
            await refreshConnectors()
        } catch {
            problem = "Couldn't rotate \(connector.label): \(error.localizedDescription)"
        }
    }

    private func revoke(_ connector: RemoteConnector) async {
        do {
            _ = try await APIClient.shared.revokeRemoteConnector(id: connector.id)
            await refreshConnectors()
        } catch {
            problem = "Couldn't revoke \(connector.label): \(error.localizedDescription)"
        }
    }
}

/// One connector: mark · label · scope chips · expiry · last use · Rotate · Revoke (R-R35).
struct RemoteConnectorRow: View {
    let connector: RemoteConnector
    var onRotate: (() -> Void)? = nil
    var onRevoke: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            RemoteAppMark(app: connector.remoteApp, size: CicadaTheme.scaled(32))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(connector.label)
                        .font(CicadaTheme.bodyFont.weight(.semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(connector.remoteApp.name)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                HStack(spacing: CicadaTheme.spacingXS) {
                    ForEach(connector.grantedScopes) { scope in
                        Text(scope.title)
                            .font(CicadaTheme.captionFont)
                            .padding(.horizontal, CicadaTheme.spacingSM)
                            .padding(.vertical, CicadaTheme.scaled(2))
                            .background(Capsule().fill(CicadaTheme.surfaceElevated))
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
                Text("\(RemoteConnectorText.expiry(connector)) · \(RemoteConnectorText.lastUsed(connector))")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer(minLength: 0)
            if connector.isActive {
                if let onRotate {
                    Button("Rotate", action: onRotate)
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                        .help("Make a new link — the old one stops working")
                }
                if let onRevoke {
                    Button("Revoke", role: .destructive, action: onRevoke)
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.danger)
                }
            }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .opacity(connector.isActive ? 1 : 0.6)
    }
}

/// An app's real mark (bundled PNG, clipped — three of them are opaque plates,
/// `LogoAssetTests.opaquePlate`) or its SF Symbol when no mark ships (R-R34).
struct RemoteAppMark: View {
    let app: RemoteApp
    var size: CGFloat = 28

    var body: some View {
        Group {
            if let logo = app.logoName, LogoImage.exists(name: logo) {
                LogoImage(name: logo, size: size)
                    .clipShape(RoundedRectangle(cornerRadius: size * 0.22))
            } else {
                Image(systemName: app.symbol)
                    .font(CicadaTheme.font(size: size * 0.5))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: size, height: size)
                    .background(RoundedRectangle(cornerRadius: size * 0.22).fill(CicadaTheme.surfaceElevated))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(app.name)
    }
}
