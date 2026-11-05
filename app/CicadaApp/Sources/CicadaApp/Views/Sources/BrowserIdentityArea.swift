import AppKit
import SwiftUI

/// ROR-114 (owner: "inside that source its easy to see what is the link where your profile is and what your handle is
/// for each … if I'm logged out Cicada should detect this") — under the head of a source read through the person's own
/// browser: whose list it is (the handle and a link to their profile, as their agent reported them), and, when the
/// last attempt met a login wall, the one line and action to fix it. Draws nothing when it has neither (DR-81).
/// DR-5: link ink is the accent's text use, the one primary is Try again; DR-59: one line each.
struct BrowserIdentityArea: View {
    let site: String
    let browser: BrowserRead
    let tryAgain: () -> Void
    var open: (URL) -> Void = { NSWorkspace.shared.open($0) }

    private var signedOut: Bool { browser.state == .signedOut }
    private var handle: String? { BrowserIdentity.display(browser.handle) }
    private var profile: URL? { BrowserIdentity.profileURL(browser.profileURL) }

    var body: some View {
        if signedOut || handle != nil || profile != nil {
            SourceConnectArea(
                primary: signedOut ? SourcePrimaryAction(title: Copy.Browser.tryAgain, action: tryAgain) : nil,
                line: signedOut ? Copy.Browser.signIn(site) : nil, lineIsAttention: signedOut
            ) {
                if handle != nil || profile != nil { identity }
            }
        }
    }

    private var identity: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "person.crop.circle")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            if let handle {
                Text(handle)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            if let profile {
                Button { open(profile) } label: { Text(Copy.Browser.openProfile) }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.accentText)
                    .help(Copy.Browser.profileHelp(site))
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: CicadaTheme.scaled(24))
    }
}

/// The decisions, with no view in them. A handle and a link arrive from an agent, so the link is checked again at the
/// last step: `ItemPlaceOpen.webURL`'s rule (a plain link with a host, no credentials), and https only.
enum BrowserIdentity {
    static func profileURL(_ raw: String?) -> URL? {
        guard let raw, let url = ItemPlaceOpen.webURL(raw), url.scheme?.lowercased() == "https" else { return nil }
        return url
    }

    /// "@name", except a handle the site writes with its own prefix ("u/name") which is shown as it is.
    static func display(_ handle: String?) -> String? {
        guard let word = handle?.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "@")),
              !word.isEmpty else { return nil }
        return word.contains("/") ? word : "@" + word
    }
}
