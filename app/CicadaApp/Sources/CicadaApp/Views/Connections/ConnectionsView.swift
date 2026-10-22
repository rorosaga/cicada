import AppKit
import SwiftUI

/// G50 — one card per provider connection. Subscriptions are probed through the
/// vendor CLI (Cicada never holds a token); API keys go to `secrets.env` in Cicada's home (never named on screen).
///
/// Credentials only (G139, R-O9): the plan, its sign-in and the keys. Engine
/// choice lives on Engines — the Max tier picker (a cost-estimate control, K4)
/// is gone and "Use for Sleep" moved there as "Auto may use my Claude plan".
///
/// Hyrum audit B1 (2026-10-22): no longer a page of its own. It is the *Plans & keys* group at the end of Settings →
/// Engines, under the anchor the page's header had (`SettingsRowID.plansAndKeys`, `page:plansAndKeys`).
struct ConnectionsView: View {
    @Environment(ConnectionsViewModel.self) private var viewModel
    @State private var keyDrafts: [String: String] = [:]
    @State private var confirmDisconnect: ConnectionStatus?
    @State private var terminalFallback = false
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    /// DR-39 — per viewer, never synced: a person who opened the key cards finds them open next time. A landing on a
    /// folded card opens it for this view only (`keysLanded`), never rewriting the person's choice.
    @AppStorage(Self.keysOpenKey) private var keysStored = false
    @State private var keysLanded = false
    private var keysOpen: Bool { keysStored || keysLanded }

    static let keysOpenKey = "cicada.plansAndKeys.keysOpen"

    /// Settings defaults (owner 2026-10-22; ruling 31, plans first; Hyrum B10): the plans, the local model and any
    /// key already saved stay open; a key nobody has saved waits under one fold. Same cards, same routes, same files.
    static func split(_ all: [ConnectionStatus]) -> (open: [ConnectionStatus], folded: [ConnectionStatus]) {
        (all.filter { !$0.isKeyBased || $0.connected }, all.filter { $0.isKeyBased && !$0.connected })
    }

    // `body` is split into `refreshButton`, `pageContent`, `cards` and the dialog's words: as one expression it sat
    // near what the type checker solves in reasonable time on a slower release runner.
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline) {
                SettingsGroupHeader(Copy.plansAndKeys)
                Spacer(minLength: CicadaTheme.spacingSM)
                refreshButton
            }
            .padding(.horizontal, CicadaTheme.spacingXS)
            pageContent
        }
        .settingsRow(.plansAndKeys)
        .onAppear { openKeysIfLanded(focus?.highlighted) }
        .onChange(of: focus?.landedNonce ?? 0) { _, _ in openKeysIfLanded(focus?.landed) }
        // No `.task { load() }`: `ConnectionsViewModel` is a thin projection
        // over `Store.connections`, already hydrated + kept live by the
        // Store — this section renders instantly from the snapshot on revisit.
        // …except a browser sign-in's row (OpenRouter): its callback can save the key while this page is
        // closed, and `/connections` is not a sync component, so that one row is re-read on each visit.
        .task { await viewModel.refreshBrowserSignInRows() }
        .onDisappear { viewModel.stopPolling() }
        // R-E28: signing out of ChatGPT runs `codex logout` in Cicada's own
        // Codex home only, so the dialog says the terminal's Codex is untouched.
        .confirmationDialog(disconnectTitle, isPresented: disconnectPresented, presenting: confirmDisconnect) { c in
            Button(Self.disconnectAction(c), role: .destructive) {
                Task { await viewModel.logout(c.id) }
            }
        } message: { c in
            Text(Self.disconnectMessage(c))
        }
    }

    /// A group header's one icon control (DR-40), where the page header's bordered button sat before B1.
    private var refreshButton: some View {
        IconButton(systemName: "arrow.clockwise", help: Copy.checkAgain, accessibilityLabel: Copy.checkPlansAndKeysAgain) {
            Task { await viewModel.load(fresh: true) }
        }
    }

    @ViewBuilder private var pageContent: some View {
        if let err = viewModel.errorMessage {
            Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
        }
        if viewModel.isLoading {
            ProgressView().frame(maxWidth: .infinity, alignment: .center)
        } else {
            cards(Self.split(viewModel.connections))
        }
    }

    private func cards(_ groups: (open: [ConnectionStatus], folded: [ConnectionStatus])) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            ForEach(groups.open) { c in card(c) }
            if !groups.folded.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    DisclosureHeader(title: Copy.useAnAPIKeyInstead, isOpen: keysOpen) {
                        if keysOpen { keysStored = false; keysLanded = false } else { keysStored = true }
                    }
                    if keysOpen {
                        VStack(spacing: CicadaTheme.spacingMD) {
                            ForEach(groups.folded) { c in card(c) }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var disconnectTitle: String {
        confirmDisconnect?.id == "chatgpt-plan"
            ? Copy.chatgptSignOutTitle
            : "Disconnect \(confirmDisconnect?.label ?? "")?"
    }

    private var disconnectPresented: Binding<Bool> {
        Binding(get: { confirmDisconnect != nil }, set: { if !$0 { confirmDisconnect = nil } })
    }

    private static func disconnectAction(_ c: ConnectionStatus) -> String {
        c.id == "chatgpt-plan" ? Copy.signOut : "Disconnect"
    }

    private static func disconnectMessage(_ c: ConnectionStatus) -> String {
        c.id == "claude-plan"
            ? Copy.claudeSignOutExplainer
            : c.id == "chatgpt-plan" ? Copy.chatgptSignOutExplainer : Copy.keyRemovedFromMac
    }

    private func card(_ c: ConnectionStatus) -> some View {
        ConnectionCard(
            connection: c,
            keyDraft: Binding(get: { keyDrafts[c.id, default: ""] }, set: { keyDrafts[c.id] = $0 }),
            pendingLogin: viewModel.pendingLogin?.connectionId == c.id ? viewModel.pendingLogin : nil,
            awaitingTerminal: viewModel.awaitingTerminal == c.id,
            awaitingBrowser: viewModel.awaitingBrowser == c.id,
            terminalFallback: terminalFallback,
            onConnect: { Task { await connect(c) } },
            onDisconnect: { confirmDisconnect = c },
            onSaveKey: { Task { await viewModel.saveKey(c.id, key: keyDrafts[c.id, default: ""]); keyDrafts[c.id] = "" } }
        )
        .settingsRow(.connection(c.id))
    }

    /// A search hit on a folded key card opens the fold, so the row it names is on screen (R-O6). On appear only the
    /// row still washed counts (`highlighted`); `landed` outlives the landing.
    private func openKeysIfLanded(_ row: SettingsRowID?) {
        guard let id = row?.item(of: "connection") else { return }
        if Self.split(viewModel.connections).folded.contains(where: { $0.id == id }) { keysLanded = true }
    }

    private func connect(_ c: ConnectionStatus) async {
        terminalFallback = false
        guard let session = await viewModel.beginLogin(c.id) else { return }
        if session.mode == "terminal", let cmd = session.command {
            terminalFallback = !openInTerminal(cmd)
        }
    }

    /// Hand the interactive browser-OAuth login to Terminal (Claude Code needs a TTY).
    /// Returns `true` if Terminal was launched, `false` if AppleScript failed and the
    /// command was copied to the clipboard as a fallback.
    @discardableResult
    private func openInTerminal(_ command: String) -> Bool {
        let script = "tell application \"Terminal\"\nactivate\ndo script \"\(command)\"\nend tell"
        if let apple = NSAppleScript(source: script) {
            var err: NSDictionary?
            apple.executeAndReturnError(&err)
            if err != nil {
                AppPasteboard.copy(command)
                return false
            }
            return true
        }
        AppPasteboard.copy(command)
        return false
    }
}

private struct ConnectionCard: View {
    let connection: ConnectionStatus
    @Binding var keyDraft: String
    let pendingLogin: LoginSession?
    let awaitingTerminal: Bool
    /// R-AG10: OpenRouter's consent page is open in the browser; the card waits for the callback to land the key.
    let awaitingBrowser: Bool
    let terminalFallback: Bool
    let onConnect: () -> Void
    let onDisconnect: () -> Void
    let onSaveKey: () -> Void

    /// R-E27: the plan's vendor mark (Claude, ChatGPT), Ollama's, and each
    /// key's vendor — one translation shared with Settings → Engines.
    private var logo: String? { ConnectionMark.logoName(connectionId: connection.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                if let logo {
                    LogoImage.platformTile(name: logo, size: 28)
                } else {
                    Image(systemName: ConnectionMark.symbol(isKeyBased: connection.isKeyBased)).frame(width: 28, height: 28)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(connection.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                    if let subtitle = connection.subtitle {
                        Text(subtitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
                Spacer()
                statusPill
            }

            if let account = connection.account, connection.connected {
                Text(account).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .privacySensitive()
            }
            if let detail = ConnectionsView.unconnectedDetail(connection) {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }

            // G63: "why does this say Connected?" — the sentence comes from the
            // backend adapter that ran the probe, so the copy can never drift
            // from the check that produced it.
            if let how = ConnectionsView.howLine(connection) {
                Text(how)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let powers = connection.powersLine {
                HStack(spacing: CicadaTheme.spacingXS) {
                    SectionLabel("Powers")
                    Text(powers)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }

            actions
        }
        .padding(CicadaTheme.spacingMD)
        // Full width like every other Settings card — `settingsCardSurface`
        // (unlike the old glass card's ScrollView) sets no width of its own.
        .frame(maxWidth: .infinity, alignment: .leading)
        .settingsCardSurface()
    }

    private var statusPill: some View {
        let (text, color): (String, Color) = !connection.available
            ? ("Not installed", CicadaTheme.textTertiary)
            : connection.connected ? ("Connected", CicadaTheme.statusColor(for: .active))
            : ("Not connected", CicadaTheme.textSecondary)
        return Text(text).font(CicadaTheme.captionFont).foregroundStyle(color)
            .padding(.horizontal, CicadaTheme.spacingSM).padding(.vertical, 2)
            .background(color.opacity(0.12)).cornerRadius(CicadaTheme.cornerRadiusSmall)
    }

    @ViewBuilder
    private var actions: some View {
        if connection.isKeyBased {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    if connection.connected {
                        Button("Remove key", role: .destructive, action: onDisconnect)
                    } else {
                        // R-AG10 (DR-40): signing in is a second way to fill the same key, so it sits before the
                        // paste field rather than replacing it. `onConnect` → `beginLogin`, whose `oauth` case
                        // opens the browser; the terminal hand-off never fires for it.
                        if connection.signsIn {
                            NeutralButton(title: Copy.signInWithOpenRouter, isDisabled: awaitingBrowser,
                                          action: onConnect)
                        }
                        SecureField("Paste API key", text: $keyDraft).textFieldStyle(.roundedBorder).frame(maxWidth: 360)
                        Button("Save", action: onSaveKey).disabled(keyDraft.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                if awaitingBrowser, !connection.connected {
                    Text(Copy.openRouterFinishInBrowser)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        } else if connection.billing == "free" {
            if !connection.connected, let cmd = connection.login?.command { CommandBox(command: cmd) }
        } else if connection.connected {
            Button(connection.login?.mode == "device-code" ? Copy.signOut : "Disconnect",
                   role: .destructive, action: onDisconnect)
        } else if !connection.available {
            EmptyView()
        } else if let pending = pendingLogin {
            DeviceCodePanel(session: pending, onRetry: onConnect)
        } else if awaitingTerminal, let cmd = connection.login?.command {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(terminalFallback
                     ? "Couldn't open Terminal — the command was copied to your clipboard. Paste it into any terminal and finish signing in; this card updates itself."
                     : "Finish signing in in the Terminal window, then this card updates itself.")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                CommandBox(command: cmd)
            }
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let cmd = connection.login?.command, connection.login?.mode == "terminal" {
                    Text("Cicada can't sign you in — Claude Code does. Run this once and this card updates itself:")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    CommandBox(command: cmd)
                }
                Button(connection.login?.mode == "device-code" ? Copy.signInWithChatGPT : "Connect",
                       action: onConnect)
                    .buttonStyle(.borderedProminent)
            }
        }
    }
}

extension ConnectionsView {
    /// The line under a card that is not connected. A key card's backend sentence names the secrets file's path and
    /// the variable the key is exported as — right for `cicada engine list`, too technical for Settings (settings
    /// defaults, owner 2026-10-22) — so the app says where the key goes in words; every other card keeps the
    /// backend's own sentence.
    static func unconnectedDetail(_ connection: ConnectionStatus) -> String? {
        guard !connection.connected else { return nil }
        if connection.login?.mode == "key" { return Copy.keyCardDetail }
        // Settings defaults pass 2: the same words for the two cards whose backend sentence names an address, a
        // file or a command (`cicada engine list` keeps those). An install hint, or a plan that reports an API key
        // instead, keeps the backend's sentence — each names the one step that fixes it.
        switch connection.id {
        case "byok-openrouter":
            return Copy.ConnectionLine.openRouterNoKey
        case "ollama-local":
            return connection.available ? Copy.ConnectionLine.localNoModel : Copy.ConnectionLine.localNotRunning
        case "claude-plan" where connection.available && (connection.detail ?? "").hasPrefix("Not signed in"):
            return Copy.ConnectionLine.claudeSignedOut
        default:
            return connection.detail
        }
    }

    /// G63's "why does this say Connected?", in words (settings defaults pass 2). The backend's `how` names the
    /// CLI, the local address or the key file's path — right for `cicada engine list`, too technical here — and may
    /// append which environment variables Cicada strips for its own calls, which Cicada handles without the person.
    /// The connected state is the same probe's; only the sentence is the app's. An unknown card keeps the backend's.
    static func howLine(_ connection: ConnectionStatus) -> String? {
        guard connection.connected else { return connection.how }
        switch connection.id {
        case "claude-plan": return Copy.ConnectionLine.claudeSignedIn
        case "chatgpt-plan": return Copy.ConnectionLine.chatgptSignedIn
        case "ollama-local": return Copy.ConnectionLine.localReady
        default:
            return connection.isKeyBased ? Copy.ConnectionLine.keySaved : connection.how
        }
    }
}
