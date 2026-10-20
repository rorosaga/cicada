import SwiftUI

/// DR-39 / DR-53 (consistency pass, 2026-10-20) — the one disclosure glyph. Every fold in the app drew its own: a
/// `chevron.down`/`chevron.right` swap at 9, 10, 11, 12 or 13 pt, or a rotated `chevron.right`, in tertiary or secondary.
/// Now one glyph: `chevron.right`, turned a quarter when open, `icon(.disclosure)` (10 pt semibold), `textTertiary`
/// unless the caller's row colours it, in a 12 pt slot so the labels after it line up whether it is open or not.
/// The turn is never animated here: a click animates only if its caller says so, and a key never does (DR-60).
struct DisclosureChevron: View {
    let isOpen: Bool
    /// Nil keeps the inherited foreground (a row that lights its text on hover lights the glyph with it).
    var color: Color? = CicadaTheme.textTertiary
    /// A fold whose panel opens ABOVE it (the Graph's Legend) points up while closed and down while open; the same
    /// glyph, turned the other way.
    var opensUpward = false

    var body: some View {
        Image(systemName: "chevron.right")
            .font(CicadaTheme.icon(.disclosure))
            .rotationEffect(.degrees(isOpen ? 90 : (opensUpward ? -90 : 0)))
            .foregroundStyle(color.map(AnyShapeStyle.init) ?? AnyShapeStyle(.foreground))
            .frame(width: CicadaTheme.iconPoints(.inline))
            .accessibilityHidden(true)
    }
}

/// DR-39 / DR-20 (consistency pass, 2026-10-20) — a section that folds. A static section is a `SectionLabel`; a section
/// the person can open is this: the chevron, the title in 12 medium `textSecondary` (`textPrimary` on hover — it is a
/// control, so it reads as one), and, while closed, a few words of what it holds in `textTertiary`, tabular ("9",
/// "· 4,770"). 28 pt tall, the whole line the hit target. Projects' sections and its Fading fold, the entity card's
/// sections, Sources' statistics and captured list, and the Inbox's settled checks all draw through it.
struct DisclosureHeader: View {
    let title: String
    /// Words beside a closed section; nil or empty says nothing.
    var summary: String? = nil
    /// Show the summary while open too (a count that stays true either way, such as Fading's).
    var summaryWhenOpen = false
    let isOpen: Bool
    var help: String? = nil
    /// Stretch the hit target to the column's width (a disclosure that heads a list).
    var fillsWidth = false
    /// What VoiceOver names when the visible words carry a count ("Settled by a check · 3" reads "Settled by a check").
    var spokenTitle: String? = nil
    let toggle: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                DisclosureChevron(isOpen: isOpen).iconHover(hovering: hovering)   // DR-64: an interactive glyph
                Text(title)
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                if let summary = summaryShown {
                    Text(summary)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
                if fillsWidth { Spacer(minLength: 0) }
            }
            .font(CicadaTheme.metaMediumFont)
            .frame(height: CicadaTheme.scaled(Self.height))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        // DR-61 / DR-63 — the pointer's hover eases on `CicadaMotion.hover`; a key never hovers, so no keyboard path
        // animates (DR-60).
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onHover { hovering = $0 }
        .help(help ?? "")
        .accessibilityLabel(spokenTitle ?? title)
        .accessibilityAddTraits(.isHeader)
        .accessibilityValue(Self.spokenValue(isOpen: isOpen, summary: summaryShown))
    }

    private var summaryShown: String? {
        guard let summary, !summary.isEmpty, !isOpen || summaryWhenOpen else { return nil }
        return summary
    }

    /// The state, then what the visible words count ("Collapsed, 4"), so VoiceOver hears "Fading 4", not "Fading".
    static func spokenValue(isOpen: Bool, summary: String?) -> String {
        let state = isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed
        let words = summary?.trimmingCharacters(in: CharacterSet(charactersIn: "· ").union(.whitespaces)) ?? ""
        return words.isEmpty ? state : "\(state), \(words)"
    }

    static let height: CGFloat = 28
}
