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
                Text(Self.explanation(for: state))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if state == .blocked, let error {
                FullDiskAccessHint(error: error)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(Self.title(for: state)). \(Self.explanation(for: state))")
        .help(Self.explanation(for: state))
    }

    static func color(for state: BrowserWatchState) -> Color {
        switch state {
        case .watching: CicadaTheme.success
        case .syncing: CicadaTheme.info
        case .stale: CicadaTheme.warning
        case .blocked, .failed: CicadaTheme.danger
        case .absent: CicadaTheme.textTertiary
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
        }
    }
}
