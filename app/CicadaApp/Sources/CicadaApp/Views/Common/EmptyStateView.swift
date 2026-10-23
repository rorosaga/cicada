import SwiftUI
import UniformTypeIdentifiers

/// G117 — one honest "nothing here, here's the one thing to do" component,
/// reused by every tab that can be empty on a fresh bank (Graph, Inbox,
/// Saved, Sources, Projects, Looks).
///
/// Two action shapes, not one, because a PLAIN closure cannot reliably open
/// the Settings window on this app's target OS — the reasoning, and the one
/// writer of the section seed, now live in `SettingsSectionLink` (G125 v3,
/// P5), which this view renders when `settingsSection` is set. The moment ANY
/// empty state needs to send the person to Settings, it must go through that
/// view, never a bare `action:` closure that calls `openSettings()` or the
/// private AppKit selector directly.
///
/// **Plain, well-set text (owner 2026-10-16; DR-50).** Painted art is retired
/// from the app ("Remove it from everywhere"), the Inbox's "all caught up"
/// included: no grass, no cloud, no worm, no card. A display title, the
/// truthful line, at most one action, centred in the space the page gives it.
/// The study room on the Sleep page and in onboarding is the app's one
/// illustration.
///
/// **One icon (2026-10-22, onboarding v2, DR-50 amendment):** a page a new person lands on may lead with one SF Symbol
/// (`systemImage`, `textTertiary`, 28 pt) — the T3 empty-state pattern: one icon, one bold sentence, one grey
/// instruction. A glyph, never art (DR-13): no illustration returns.
struct EmptyStateView: View {
    var systemImage: String? = nil
    let title: String
    let message: String
    var actionLabel: String? = nil
    var action: (() -> Void)? = nil
    /// Set instead of `actionLabel`/`action` when the one thing to do is
    /// "open Settings, on this section."
    var settingsSection: SettingsHome? = nil
    /// Track I T5 (R-IA27) — set on a page an export can fill (Graph, Feed,
    /// Sources): the view takes a dropped file and hands it to the one intake
    /// with that page's own origin. Nil (Inbox) attaches no drop target at all.
    var onDropFiles: (([URL]) -> Void)? = nil
    /// Off where the instruction already says to drop (DR-38: never say it twice).
    var showsDropHint = true
    @State private var dropTargeted = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(CicadaTheme.font(size: EmptyStateLayout.iconSize, weight: .regular))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.bottom, CicadaTheme.spacingXS)
                    .accessibilityHidden(true)
            }
            Text(title)
                .font(CicadaTheme.displayFont(size: EmptyStateLayout.titleSize))
                .tracking(CicadaTheme.displayTracking(size: EmptyStateLayout.titleSize))
                .foregroundStyle(CicadaTheme.textPrimary)
                .multilineTextAlignment(.center)
                .accessibilityAddTraits(.isHeader)
            Text(message)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            if let section = settingsSection, let actionLabel {
                SettingsSectionLink(home: section, label: actionLabel, prominent: true)
                    .padding(.top, CicadaTheme.spacingSM)
            } else if let actionLabel, let action {
                PrimaryActionButton(title: actionLabel, action: action)
                    .padding(.top, CicadaTheme.spacingSM)
            }
            if onDropFiles != nil, showsDropHint {
                Label(Copy.emptyStateDropHint, systemImage: "tray.and.arrow.down")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(dropTargeted ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.spacingXS)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(EmptyStateLayout.maxWidth))
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(minHeight: CicadaTheme.scaled(EmptyStateLayout.minHeight))
        .contentShape(Rectangle())
        .modifier(EmptyStateDrop(onDropFiles: onDropFiles, targeted: $dropTargeted))
    }
}

/// Track I T5 (R-IA27) — an empty page that can be filled by an export takes the
/// drop itself; one that cannot (Inbox) attaches no target, so the window's
/// handler still gets the drop.
private struct EmptyStateDrop: ViewModifier {
    let onDropFiles: (([URL]) -> Void)?
    @Binding var targeted: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if let onDropFiles {
            content.onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
                IntakeDrop.load(providers) { onDropFiles($0) }
                return true
            }
        } else {
            content
        }
    }
}

/// The empty state's set, as numbers (`EmptyStateViewTests`). Points at `uiScale == 1`; the view scales them.
enum EmptyStateLayout {
    /// DR-50: the empty-state title is the display face at 22 pt.
    static let titleSize: CGFloat = 22
    /// The one icon over the title (2026-10-22).
    static let iconSize: CGFloat = 28
    /// A short measure, so the one line reads as a sentence, not a banner.
    static let maxWidth: CGFloat = 420
    /// Inside a scrolling list (Projects, Sources) the page offers no height of its own; this keeps the words off the
    /// top edge, centred in a band rather than pinned under the eyebrow.
    static let minHeight: CGFloat = 360
}
