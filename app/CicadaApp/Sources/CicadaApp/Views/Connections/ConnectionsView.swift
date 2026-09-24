import AppKit
import SwiftUI

/// G50 — one card per provider connection. Subscriptions are probed through the
/// vendor CLI (Cicada never holds a token); API keys go to ~/.cicada/secrets.env.
///
/// Credentials only (G139, R-O9): the plan, its sign-in and the keys. Engine
/// choice lives on Engines — the Max tier picker (a cost-estimate control, K4)
/// is gone and "Use for Sleep" moved there as "Auto may use my Claude plan".
struct ConnectionsView: View {
    @Environment(ConnectionsViewModel.self) private var viewModel
    @State private var keyDrafts: [String: String] = [:]
    @State private var confirmDisconnect: ConnectionStatus?
    @State private var terminalFallback = false

    var body: some View {
        SettingsPage(section: .plansAndKeys, trailing: AnyView(
            Button { Task { await viewModel.load(fresh: true) } } label: { Image(systemName: "arrow.clockwise") }
                .help("Check again")
        )) {
            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            }
            if viewModel.isLoading {
                ProgressView().frame(maxWidth: .infinity, alignment: .center)
            } else {
                VStack(spacing: CicadaTheme.spacingMD) {
                    ForEach(viewModel.connections) { c in
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
                }
            }
        }
        // No `.task { load() }`: `ConnectionsViewModel` is a thin projection
        // over `Store.connections`, already hydrated + kept live by the
        // Store — this section renders instantly from the snapshot on revisit.
        .onDisappear { viewModel.stopPolling() }
        // R-E28: signing out of ChatGPT runs `codex logout` in Cicada's own
        // Codex home only, so the dialog says the terminal's Codex is untouched.
        .confirmationDialog(confirmDisconnect?.id == "chatgpt-plan"
                                ? Copy.chatgptSignOutTitle
                                : "Disconnect \(confirmDisconnect?.label ?? "")?",
                            isPresented: Binding(get: { confirmDisconnect != nil }, set: { if !$0 { confirmDisconnect = nil } }),
                            presenting: confirmDisconnect) { c in
            Button(c.id == "chatgpt-plan" ? Copy.signOut : "Disconnect", role: .destructive) {
                Task { await viewModel.logout(c.id) }
            }
        } message: { c in
            Text(c.id == "claude-plan"
                 ? "Runs `claude auth logout`. Claude Code will ask you to sign in again next time you open it."
                 : c.id == "chatgpt-plan" ? Copy.chatgptSignOutExplainer : "Removes the key from ~/.cicada/secrets.env.")
        }
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
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
                return false
            }
            return true
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(command, forType: .string)
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
                    Text(connection.priceLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                Spacer()
                statusPill
            }

            if let account = connection.account, connection.connected {
                Text(account).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .privacySensitive()
            }
            if let detail = connection.detail, !connection.connected {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }

            // G63: "why does this say Connected?" — the sentence comes from the
            // backend adapter that ran the probe, so the copy can never drift
            // from the check that produced it.
            if let how = connection.how {
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
