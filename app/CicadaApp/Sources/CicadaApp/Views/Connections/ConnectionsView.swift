import AppKit
import SwiftUI

/// G50 — one card per provider connection. Subscriptions are probed through the
/// vendor CLI (Cicada never holds a token); API keys go to ~/.cicada/secrets.env.
struct ConnectionsView: View {
    @Environment(ConnectionsViewModel.self) private var viewModel
    @State private var keyDrafts: [String: String] = [:]
    @State private var confirmDisconnect: ConnectionStatus?
    @State private var terminalFallback = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageHeader(title: "Plans & keys",
                       subtitle: "What Cicada bills against. Subscriptions sign in through their own CLI — Cicada never sees the token.") {
                Button { Task { await viewModel.load(fresh: true) } } label: { Image(systemName: "arrow.clockwise") }
            }

            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            }

            if viewModel.isLoading {
                ProgressView().frame(maxWidth: .infinity, alignment: .center)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingMD) {
                        ForEach(viewModel.connections) { c in
                            ConnectionCard(
                                connection: c,
                                keyDraft: Binding(get: { keyDrafts[c.id, default: ""] }, set: { keyDrafts[c.id] = $0 }),
                                pendingLogin: viewModel.pendingLogin?.connectionId == c.id ? viewModel.pendingLogin : nil,
                                awaitingTerminal: viewModel.awaitingTerminal == c.id,
                                terminalFallback: terminalFallback,
                                onConnect: { Task { await connect(c) } },
                                onDisconnect: { confirmDisconnect = c },
                                onSaveKey: { Task { await viewModel.saveKey(c.id, key: keyDrafts[c.id, default: ""]); keyDrafts[c.id] = "" } },
                                onTier: { tier in Task { await viewModel.setTier(c.id, tier: tier) } }
                            )
                        }
                    }
                }
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingLG)
        // No `.task { load() }`: `ConnectionsViewModel` is a thin projection
        // over `Store.connections`, already hydrated + kept live by the
        // Store — this tab renders instantly from the snapshot on revisit.
        .onDisappear { viewModel.stopPolling() }
        .confirmationDialog("Disconnect \(confirmDisconnect?.label ?? "")?",
                            isPresented: Binding(get: { confirmDisconnect != nil }, set: { if !$0 { confirmDisconnect = nil } }),
                            presenting: confirmDisconnect) { c in
            Button("Disconnect", role: .destructive) { Task { await viewModel.logout(c.id) } }
        } message: { c in
            Text(c.id == "claude-plan"
                 ? "Runs `claude auth logout`. Claude Code will ask you to sign in again next time you open it."
                 : c.id == "chatgpt-plan" ? "Runs `codex logout`." : "Removes the key from ~/.cicada/secrets.env.")
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
    let terminalFallback: Bool
    let onConnect: () -> Void
    let onDisconnect: () -> Void
    let onSaveKey: () -> Void
    let onTier: (String?) -> Void

    private var logo: String? {
        switch connection.id {
        case "claude-plan": "claude-code"
        case "chatgpt-plan": "codex"
        default: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                if let logo {
                    LogoImage(name: logo, size: 28).cornerRadius(6)
                } else {
                    Image(systemName: connection.isKeyBased ? "key.fill" : "cpu").frame(width: 28, height: 28)
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
            }
            if let note = connection.priceNote, connection.connected, connection.priceUsdMonth == nil {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
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
                    Text("POWERS")
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .tracking(1.1)
                    Text(powers)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }

            if connection.showsTierPicker {
                Picker("Your Max tier (for cost estimates only)",
                       selection: Binding(get: { connection.tier ?? "" },
                                          set: { onTier($0.isEmpty ? nil : $0) })) {
                    Text("Pick tier…").tag("")
                    Text("5x").tag("5x")
                    Text("20x").tag("20x")
                }
                .pickerStyle(.segmented).frame(maxWidth: 300)
                Text("Your Max tier (for cost estimates only)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            actions
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
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
            HStack(spacing: CicadaTheme.spacingSM) {
                if connection.connected {
                    Button("Remove key", role: .destructive, action: onDisconnect)
                } else {
                    SecureField("Paste API key", text: $keyDraft).textFieldStyle(.roundedBorder).frame(maxWidth: 360)
                    Button("Save", action: onSaveKey).disabled(keyDraft.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        } else if connection.billing == "free" {
            if !connection.connected, let cmd = connection.login?.command { CommandBox(command: cmd) }
        } else if connection.connected {
            Button("Disconnect", role: .destructive, action: onDisconnect)
        } else if !connection.available {
            EmptyView()
        } else if let pending = pendingLogin {
            deviceCode(pending)
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
                Button("Connect", action: onConnect).buttonStyle(.borderedProminent)
            }
        }
    }

    private func deviceCode(_ s: LoginSession) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if s.state == "failed" {
                Text(s.detail ?? "Sign-in failed").foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            } else if let code = s.code {
                Text("Enter this code in your browser:").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                HStack(spacing: CicadaTheme.spacingMD) {
                    Text(code).font(CicadaTheme.monoFont.weight(.bold)).textSelection(.enabled)
                    if let url = s.url.flatMap(URL.init(string:)) { Link("Open sign-in page", destination: url) }
                }
                ProgressView().controlSize(.small)
            } else {
                HStack { ProgressView().controlSize(.small); Text("Starting `codex login --device-auth`…").font(CicadaTheme.captionFont) }
                if !s.rawOutput.isEmpty { Text(s.rawOutput).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary) }
            }
        }
    }
}
