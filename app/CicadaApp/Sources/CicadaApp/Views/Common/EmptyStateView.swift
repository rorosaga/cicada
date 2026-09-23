import SwiftUI
import UniformTypeIdentifiers

/// G117 — one honest "nothing here, here's the one thing to do" component,
/// reused by every tab that can be empty on a fresh bank (Graph, Inbox,
/// Feed, Sources — Sleep's own desk already handles zero, G125). The
/// bookworm at `.happy` reads as reassurance, not an error.
///
/// Two action shapes, not one, because a PLAIN closure cannot reliably open
/// the Settings window on this app's target OS — the reasoning, and the one
/// writer of the section seed, now live in `SettingsSectionLink` (G125 v3,
/// P5), which this view renders when `settingsSection` is set. The moment ANY
/// empty state needs to send the person to Settings, it must go through that
/// view, never a bare `action:` closure that calls `openSettings()` or the
/// private AppKit selector directly.
///
/// **G137 — the one surface the Meadow foundation lands on in M1.** Grass
/// grows in the two bottom corners and one cloud drifts behind the bookworm,
/// which stays the focal point because it carries the state (pixel art at
/// `.interpolation(.none)` beside a painting at `.high` — two languages in one
/// frame by the owner's brief, kept apart by size and opacity). The words sit
/// on a `surface` card, never directly on paint, so a grass corner reaching
/// under them in a short window is behind a card, not behind a sentence. The
/// title is the display serif; the one action is the page's one prominent
/// action, and it lifts on hover because it opens something.
struct EmptyStateView: View {
    let title: String
    let message: String
    var actionLabel: String? = nil
    var action: (() -> Void)? = nil
    /// Set instead of `actionLabel`/`action` when the one thing to do is
    /// "open Settings, on this section."
    var settingsSection: SettingsSection? = nil
    /// Track I T5 (R-IA27) — set on a page an export can fill (Graph, Feed,
    /// Sources): the card takes a dropped file and hands it to the one intake
    /// with that page's own origin. Nil (Inbox) attaches no drop target at all.
    var onDropFiles: (([URL]) -> Void)? = nil
    @State private var dropTargeted = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            ZStack {
                DriftingCloud(art: EmptyStateLayout.cloud, width: CicadaTheme.scaled(EmptyStateLayout.cloudWidth))
                    .offset(x: CicadaTheme.scaled(EmptyStateLayout.cloudOffset.width),
                            y: CicadaTheme.scaled(EmptyStateLayout.cloudOffset.height))
                BookwormView(state: .happy, pointSize: EmptyStateLayout.wormPointSize)
            }
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                    .font(CicadaTheme.displayFont(size: 26))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .multilineTextAlignment(.center)
                Text(message)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                if let section = settingsSection, let actionLabel {
                    SettingsSectionLink(section: section, label: actionLabel, prominent: true)
                        .hoverLift()
                        .padding(.top, CicadaTheme.spacingXS)
                } else if let actionLabel, let action {
                    PrimaryActionButton(title: actionLabel, action: action)
                        .hoverLift()
                        .padding(.top, CicadaTheme.spacingXS)
                }
                if onDropFiles != nil {
                    Label(Copy.emptyStateDropHint, systemImage: "tray.and.arrow.down")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(dropTargeted ? CicadaTheme.meadow : CicadaTheme.textTertiary)
                        .padding(.top, CicadaTheme.spacingXS)
                }
            }
            .padding(CicadaTheme.spacingLG)
            .frame(maxWidth: .infinity)
            .background(CicadaTheme.surface,
                        in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .stroke(CicadaTheme.border, lineWidth: 1))
            .modifier(EmptyStateDrop(onDropFiles: onDropFiles, targeted: $dropTargeted))
        }
        .frame(maxWidth: 360)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background { GrassCorners(height: EmptyStateLayout.cornerHeight) }
        .clipped()
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

/// The empty state's composition as numbers, so "the bookworm stays the
/// focal point" is a test (`EmptyStateViewTests`), not a hope. Points at
/// `uiScale == 1`; the view scales them.
enum EmptyStateLayout {
    /// A multiple of 24 keeps the sprite's cells integer (G107 R3).
    static let wormPointSize: CGFloat = 96
    static let cloud: MeadowArt = .cloud2
    /// Wider than the worm so it reads as sky; at most twice as wide so it
    /// never reads as a second character.
    static let cloudWidth: CGFloat = 180
    /// Up and to the left: the cloud peeks out from behind the worm's head.
    static let cloudOffset = CGSize(width: -36, height: -30)
    static let cornerHeight: CGFloat = 130
}
