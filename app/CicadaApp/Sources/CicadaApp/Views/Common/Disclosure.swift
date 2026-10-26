import AppKit
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
    /// A mark between the chevron and the title — the Inbox's kind glyph, said once for its group (inbox v2).
    var leading: AnyView? = nil
    let toggle: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        // Inbox v2 (2026-10-26): the fold moves at its source — a click eases it open on `CicadaMotion.disclosure`, a
        // key (Space with Full Keyboard Access) or an assistive press lands in one frame (DR-60, `DisclosureMotion`).
        // A caller that already moves its own way (Projects' `groupExpand`) keeps it: the inner transaction wins.
        Button { DisclosureMotion.toggle(opening: !isOpen, reduceMotion: reduceMotion, toggle) } label: {
            HStack(spacing: CicadaTheme.scaled(6)) {
                DisclosureChevron(isOpen: isOpen).iconHover(hovering: hovering)   // DR-64: an interactive glyph
                if let leading { leading }
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
        .modifier(AssistivePress(action: { Instant.run(toggle) }))
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

/// DR-53 (consistency pass, round 2, 2026-10-20) — a fold whose only control is its glyph, at the end of a row that
/// itself opens something else (Projects' "Around this project": the row opens the page, the glyph unfolds its specs).
/// `IconButton`'s 28 pt target and hover (DR-69), drawing `DisclosureChevron` — it swapped `chevron.down`/`chevron.right`
/// at 14 pt until then. Its help names what it opens or closes; VoiceOver hears that and the state.
struct DisclosureButton: View {
    let isOpen: Bool
    let help: String
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button { DisclosureMotion.toggle(opening: !isOpen, reduceMotion: reduceMotion, action) } label: {
            DisclosureChevron(isOpen: isOpen, color: hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .iconHover(hovering: hovering)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                    .fill(hovering ? CicadaTheme.bgSelected : Color.clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(help)
        .accessibilityLabel(help)
        .accessibilityValue(isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed)
        .modifier(AssistivePress(action: { Instant.run(action) }))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// How a fold moves (inbox v2, owner 2026-10-26: "When I open the drop-downs, it can be smoother"). A pointer's click
/// eases it — the content grows out of its header and fades in (`disclosureReveal()`), and whatever sits below slides
/// down with it, on `CicadaMotion.disclosure`; closing is quicker than opening (DR-65). A key lands in one frame (DR-60):
/// the event running the action says which it was, as `LooksZoom` reads it. Reduce Motion keeps only a short fade
/// (DR-66). Every `DisclosureHeader` and `DisclosureButton` toggles through this, so every fold in the app moves alike.
enum DisclosureMotion {
    enum Trigger: Equatable { case pointer, keyboard }

    static func trigger(for type: NSEvent.EventType?) -> Trigger {
        type == .keyDown || type == .keyUp ? .keyboard : .pointer
    }

    /// The animation a toggle runs under, or nil for one frame.
    static func animation(_ trigger: Trigger, opening: Bool, reduceMotion: Bool) -> Animation? {
        trigger == .keyboard ? nil : CicadaMotion.disclosure(opening: opening, reduceMotion: reduceMotion)
    }

    @MainActor
    static func toggle(opening: Bool, reduceMotion: Bool, trigger: Trigger? = nil, _ body: () -> Void) {
        let resolved = trigger ?? Self.trigger(for: NSApp.currentEvent?.type)
        if let animation = animation(resolved, opening: opening, reduceMotion: reduceMotion) {
            withAnimation(animation, body)
        } else {
            Instant.run(body)
        }
    }
}

/// A fold's content arriving and leaving: its height grows from 0 to its own (the rows below ease down with it, no
/// jump) while it fades in, clipped to what has grown so nothing draws over the next row. Under Reduce Motion only
/// the fade (DR-66). Put it on the view a fold inserts: `if isOpen { content.disclosureReveal() }`.
extension View {
    func disclosureReveal() -> some View { modifier(DisclosureRevealTransition()) }
}

private struct DisclosureRevealTransition: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.transition(reduceMotion ? .opacity
            : .modifier(active: DisclosureReveal(progress: 0), identity: DisclosureReveal(progress: 1)))
    }
}

/// `progress` 0…1 of a fold's content: that share of its height, at that opacity. Animatable, so a transition
/// interpolates it frame by frame.
struct DisclosureReveal: ViewModifier, Animatable {
    var progress: Double

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    func body(content: Content) -> some View {
        DisclosureRevealLayout(progress: progress) { content }
            .clipShape(DisclosureRevealClip(open: progress >= 1))
            .opacity(progress)
    }
}

/// Reports `progress` of its content's natural height and places the content at its top, so the stack around it
/// moves by exactly what has grown.
struct DisclosureRevealLayout: Layout {
    var progress: Double

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let child = subviews.first else { return .zero }
        let size = child.sizeThatFits(ProposedViewSize(width: proposal.width, height: nil))
        return CGSize(width: size.width, height: size.height * max(0, min(1, progress)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin, anchor: .topLeading,
                              proposal: ProposedViewSize(width: bounds.width, height: nil))
    }
}

/// The clip while a fold moves; once fully open it clips nothing, so a ring or hover fill at an edge is never cut.
private struct DisclosureRevealClip: Shape {
    let open: Bool

    func path(in rect: CGRect) -> Path {
        Path(open ? rect.insetBy(dx: -10_000, dy: -10_000) : rect)
    }
}
