import SwiftUI

// MARK: - The one soft card (owner 2026-11-23, DESIGN_RULES §9: "i would copy more the ui of superwhisper look"; asked
// whether the sidebar and the lists should follow: "sure.")
//
// Every list item that is a thing with words and a source wears this one chrome: a generous radius (`radiusLarge`), a fill
// one step above its ground, a hairline ring — never a shadow (DR-9, DR-10) — and the same padding, hover and selection.
// `PageCardSurface` (Related and References on an entity page), `OriginCardChrome` (a history's cards, the Sleep page's
// episode and chat cards) and the lists that adopt it (the Feed's saved items, the Inbox's questions, Home's lead
// question) are all this modifier with different arguments, so a token changes in one place.

/// How a card sits in its list. `current` is the newest of a history — the accent ring and wash (DESIGN_RULES §9
/// 2026-11-23, the seventh accent use, `OriginCard` alone); `plain` is an item of a list that is not a history; `past`
/// fades — an older wording, an episode Sleep already read.
enum OriginCardTone: Equatable { case current, plain, past }

struct SoftCardChrome: ViewModifier {
    /// What the card stands on. `page` is the page's own ground (`bgFocus`, hover `bgHover`); `nested` is a card inside
    /// another card, one step higher so two layers read (`bgOption`, hover `bgButton`).
    enum Ground { case page, nested }
    /// `roomy` holds two lines of words and a meta line; `snug` holds one line of a title with its quiet line.
    /// An item is a `card` (`radiusLarge`); a container that groups rows or facts is a `block` (`cornerRadius`, §3.6: "grouped
    /// blocks"), the same fill, ring and hover.
    enum Shape { case card, block }
    /// `none` for a card that sets its own padding (Home's lead question, which holds a picture and two buttons).
    enum Inset { case roomy, snug, none }

    var ground: Ground = .page
    var shape: Shape = .card
    var tone: OriginCardTone = .plain
    var inset: Inset = .roomy
    var hovering = false
    /// Kept at full strength although `past` (an expanded card).
    var held = false
    /// The card the pointer or the keyboard has open: the selected-row fill (`bgSelected`), never the accent.
    var selected = false
    /// Stretches to the column; a card in a flow keeps its own width.
    var fillsWidth = false

    /// The past cards' fade at rest.
    static var pastOpacity: Double { 0.55 }

    func body(content: Content) -> some View {
        let shape = CicadaTheme.shape(self.shape == .card ? CicadaTheme.radiusLarge : CicadaTheme.cornerRadius)
        let padded = content
            .padding(.horizontal, inset == .none ? 0 : CicadaTheme.spacingMD + (inset == .roomy ? CicadaTheme.scaled(2) : 0))
            .padding(.vertical, inset == .none ? 0 : (inset == .roomy ? CicadaTheme.spacingMD : CicadaTheme.spacingSM))
        (fillsWidth ? AnyView(padded.frame(maxWidth: .infinity, alignment: .leading)) : AnyView(padded))
            .background {
                ZStack {
                    shape.fill(fill)
                    if tone == .current { shape.fill(CicadaTheme.accent.opacity(0.06)) }
                }
            }
            .overlay(shape.strokeBorder(ring, lineWidth: 1))
            .opacity(tone == .past && !hovering && !held ? Self.pastOpacity : 1)
            .contentShape(shape)
    }

    private var fill: Color {
        if selected { return CicadaTheme.bgSelected }
        let resting = ground == .page ? CicadaTheme.bgFocus : CicadaTheme.bgOption
        let lifted = ground == .page ? CicadaTheme.bgHover : CicadaTheme.bgButton
        return hovering && tone != .current ? lifted : resting
    }

    private var ring: Color {
        tone == .current ? CicadaTheme.accent.opacity(0.55) : CicadaTheme.ring(hovering || selected ? .strong : .resting)
    }
}

extension View {
    /// The one card chrome (see the file's note).
    func softCard(ground: SoftCardChrome.Ground = .page, shape: SoftCardChrome.Shape = .card, tone: OriginCardTone = .plain,
                  inset: SoftCardChrome.Inset = .roomy, hovering: Bool = false, held: Bool = false,
                  selected: Bool = false, fillsWidth: Bool = false) -> some View {
        modifier(SoftCardChrome(ground: ground, shape: shape, tone: tone, inset: inset, hovering: hovering, held: held,
                                selected: selected, fillsWidth: fillsWidth))
    }
}

/// The gap between two cards of a list (owner reference: about 12 pt, no divider between them).
extension CicadaTheme {
    static var cardGap: CGFloat { spacingMD }
}

/// A list item as a card that tracks its own pointer hover (the hover fill eases on `CicadaMotion.hover`, only the
/// pointer's; a selection moved by a key never animates, DR-60). `selected` is the open item, `bgSelected`, no accent.
struct SoftCardRow: ViewModifier {
    var ground: SoftCardChrome.Ground = .page
    var inset: SoftCardChrome.Inset = .roomy
    var selected = false
    var tone: OriginCardTone = .plain

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .softCard(ground: ground, tone: tone, inset: inset, hovering: hovering, selected: selected, fillsWidth: true)
            .onHover { hovering = $0 }
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

extension View {
    func softCardRow(ground: SoftCardChrome.Ground = .page, inset: SoftCardChrome.Inset = .roomy,
                     selected: Bool = false, tone: OriginCardTone = .plain) -> some View {
        modifier(SoftCardRow(ground: ground, inset: inset, selected: selected, tone: tone))
    }
}
