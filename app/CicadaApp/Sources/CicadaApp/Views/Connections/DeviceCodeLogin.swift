import AppKit
import SwiftUI

/// R-E28 — "Sign in with ChatGPT", in the app. The backend runs `codex login
/// --device-auth` in Cicada's own Codex home and parses the one-time code and
/// the verification link out of its output; this turns that session into
/// what the card shows, and decides when the link may open.
enum DeviceCodeLogin {
    enum Phase: Equatable {
        case starting
        case showCode(code: String, url: URL)
        case failed(String)
        case done
    }

    /// The link comes from a CLI's stdout, so it opens only when it is an
    /// https page on OpenAI's own sign-in hosts — never another scheme or a
    /// host that merely contains the name.
    static let trustedHostSuffixes = ["openai.com", "chatgpt.com"]

    static func verificationURL(_ raw: String?) -> URL? {
        guard let raw, let url = URL(string: raw), url.scheme == "https",
              let host = url.host?.lowercased() else { return nil }
        let trusted = trustedHostSuffixes.contains { host == $0 || host.hasSuffix(".\($0)") }
        return trusted ? url : nil
    }

    static func phase(of session: LoginSession) -> Phase {
        switch session.state {
        case "done":
            return .done
        case "failed":
            let detail = (session.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return .failed(detail.isEmpty ? Copy.deviceCodeFailed : detail)
        default:
            if let code = session.code, !code.isEmpty, let url = verificationURL(session.url) {
                return .showCode(code: code, url: url)
            }
            return .starting
        }
    }

    /// What the sign-in printed, shown only while no code has parsed — the
    /// safety net for a Codex release that words its prompt differently.
    static func printedFallback(_ session: LoginSession) -> String? {
        guard case .starting = phase(of: session) else { return nil }
        let text = session.rawOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    /// The link to open automatically — once per sign-in, and only once the
    /// code is on screen to type into it.
    static func urlToOpen(_ session: LoginSession, alreadyOpened: String?) -> URL? {
        guard alreadyOpened != session.sessionId,
              case let .showCode(_, url) = phase(of: session) else { return nil }
        return url
    }
}

/// The card body while a ChatGPT sign-in is in flight. The existing 2 s poll
/// (`ConnectionsViewModel.pollDeviceLogin`) replaces `session` and, on
/// `done`, re-probes — which is what flips the card to Signed in.
struct DeviceCodePanel: View {
    let session: LoginSession
    let onRetry: () -> Void
    // Explicit `= nil`: a private stored property the memberwise init would
    // have to take makes that init private, and `ConnectionsView` (another
    // file) builds this panel — the same shape `CommandBox` relies on.
    @State private var openedFor: String? = nil
    @State private var copiedCode: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            switch DeviceCodeLogin.phase(of: session) {
            case .starting:
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.deviceCodeStarting)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                // Final review H2: if Codex's wording ever changes so no code
                // parses, its own words (already stripped of colour codes by
                // the backend) still reach the person instead of a spinner.
                if let printed = DeviceCodeLogin.printedFallback(session) {
                    Text(Copy.deviceCodeRawFallback)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    Text(printed)
                        .font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textSecondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            case let .showCode(code, url):
                Text(Copy.deviceCodeInstructions)
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                HStack(spacing: CicadaTheme.spacingMD) {
                    Text(code)
                        .font(CicadaTheme.font(size: 18, weight: .bold, design: .monospaced))
                        .textSelection(.enabled)
                        .accessibilityLabel("Sign-in code \(code)")
                    Button(copiedCode == code ? Copy.copied : Copy.copyCode) { copy(code) }
                        .buttonStyle(.bordered).controlSize(.small)
                    Link(Copy.openSignInPage, destination: url).font(CicadaTheme.captionFont)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.deviceCodeWaiting)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            case let .failed(message):
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                Text(Copy.deviceCodeFailedHint)
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Button(Copy.tryAgain, action: onRetry).buttonStyle(.bordered)
            case .done:
                Text(Copy.deviceCodeDone)
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        // Keyed on BOTH fields: the code and the link can arrive on different polls.
        .task(id: "\(session.code ?? "")|\(session.url ?? "")") { openOnce() }
    }

    private func openOnce() {
        guard let url = DeviceCodeLogin.urlToOpen(session, alreadyOpened: openedFor) else { return }
        openedFor = session.sessionId
        NSWorkspace.shared.open(url)
    }

    private func copy(_ code: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        copiedCode = code
    }
}
