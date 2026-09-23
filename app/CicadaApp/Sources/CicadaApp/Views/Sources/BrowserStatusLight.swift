import SwiftUI

/// G129 — the per-browser status light.
///
/// A browser row used to say only "Connected", which was true of a channel that
/// had synced once in July and been dead since. These states are the questions
/// a person actually has about a sync: is it live, is it behind, is it broken,
/// and if it is broken is there anything I can do. The one state with something
/// to do (`blocked`) carries the fix beside it, which is the same rule the
/// import panels follow.
struct BrowserStatusLight: View {
    let state: BrowserWatchState
    let error: BrowserFileError?
    /// Compact hides the sentence and keeps the dot — for a dense list row.
    var compact: Bool = false
    /// R-LS26 — which channel wears the light, so a watched folder or Wispr Flow
    /// explains itself in its own words instead of a browser's. `nil` keeps the
    /// browser sentences.
    var channelId: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Circle()
                    .fill(Self.color(for: state))
                    .frame(width: 7, height: 7)
                    .opacity(state == .syncing ? 0.5 : 1)
                if !compact {
                    Text(Self.title(for: state))
                        .font(CicadaTheme.headingFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                }
            }
            if !compact {
                Text(Self.explanation(for: state, channelId: channelId))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if state == .blocked, let error {
                FullDiskAccessHint(error: error)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(Self.title(for: state)). \(Self.explanation(for: state, channelId: channelId))")
        .help(Self.explanation(for: state, channelId: channelId))
    }

    static func color(for state: BrowserWatchState) -> Color {
        switch state {
        case .watching: CicadaTheme.success
        case .syncing: CicadaTheme.info
        case .stale: CicadaTheme.warning
        case .blocked, .failed: CicadaTheme.danger
        case .absent, .off: CicadaTheme.textTertiary
        }
    }

    static func title(for state: BrowserWatchState) -> String {
        switch state {
        case .watching: "Watching"
        case .syncing: "Syncing…"
        case .stale: "Behind"
        case .blocked: "Can't read"
        case .failed: "Sync failed"
        case .absent: "Not installed"
        case .off: "Off"
        }
    }

    /// Says what the state means for the person, not what the code did.
    static func explanation(for state: BrowserWatchState) -> String {
        switch state {
        case .watching:
            "Anything you bookmark shows up in the Sleep queue within a few seconds."
        case .syncing:
            "Reading what changed."
        case .stale:
            "This browser's bookmarks changed and Cicada hasn't caught up. Sync now."
        case .blocked:
            "Cicada isn't allowed to read this browser's file."
        case .failed:
            "The last sync didn't finish. Try Sync now — the details are below."
        case .absent:
            "This browser isn't installed on this Mac, or has no bookmarks yet."
        case .off:
            "Cicada reads this browser only after you turn it on. Sync now brings its bookmarks in and keeps watching."
        }
    }

    /// The local sources' own sentences (G133 / G134); every other channel keeps
    /// the browser's.
    static func explanation(for state: BrowserWatchState, channelId: String?) -> String {
        if let channelId, channelId.hasPrefix("folder:") {
            switch state {
            case .watching: return "Edits in this folder reach the Sleep queue within a few seconds."
            case .syncing: return "Reading what changed."
            case .stale: return "This folder changed and Cicada hasn't caught up. Sync now."
            case .blocked: return "Cicada isn't allowed to read this folder."
            case .failed: return "The last sync didn't finish. Try Sync now."
            case .absent: return "This folder isn't on this Mac."
            case .off: return "Cicada reads this folder only after you turn it on."
            }
        }
        if channelId == LocalSourceWatcher.wisprChannel {
            switch state {
            case .watching: return "New meetings and notes arrive within a few minutes."
            case .syncing: return "Reading what's new in Wispr Flow."
            case .stale: return "Wispr Flow has something new that Cicada hasn't read yet."
            case .blocked: return "Cicada isn't allowed to read Wispr Flow's data."
            case .failed: return "The last sync didn't finish. Try Sync now."
            case .absent: return "Wispr Flow isn't on this Mac."
            case .off: return "Cicada reads Wispr Flow only after you turn it on."
            }
        }
        return explanation(for: state)
    }
}
