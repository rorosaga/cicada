import SwiftUI

// MARK: - Cards on an entity page (owner 2026-11-23, DESIGN_RULES §9: "i would copy more the ui of superwhisper look")
//
// Related and References rows are soft rounded cards on a slightly lighter fill with a hairline ring (DR-9, DR-12), each
// leading with its mark or picture, then its title and a quiet meta line. This page only: Key Facts stays a plain list
// (its chips and source clusters carry it), and no other page changes.

/// The one card surface of an entity page: `bgFocus` on the page's ground, a resting ring, `cornerRadius`, the padding
/// of a row (DR-12). Hover takes the row-hover fill where the card is a control.
struct PageCardSurface: ViewModifier {
    var hovering = false

    func body(content: Content) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        content
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(shape.fill(hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus))
            .ringed(.resting, in: shape)
            .contentShape(shape)
    }
}

extension View {
    func pageCard(hovering: Bool = false) -> some View { modifier(PageCardSurface(hovering: hovering)) }
}

/// A Related item: the page's picture (a person's photo or initials, a company's logo), its name, and what is said of
/// the link. A click opens the page as a chip does.
struct RelatedCard: View {
    let model: RelatedCardModel
    /// The list's picture column in units (`slotWidth`), 0 when no card draws a picture: every card holds it, so every
    /// name starts at one edge.
    let slot: CGFloat

    @Environment(\.openURL) private var openURL
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(Store.self) private var store: Store?
    @State private var hovering = false
    @FocusState private var focused: Bool

    /// 28 units, or a media page's 3:2 well (42) when some card in the list is one.
    static func slotWidth(_ drawn: [EntityType]) -> CGFloat {
        drawn.isEmpty ? 0 : EntityPictureLayout.frame(drawn.contains(.media) ? .media : .project, size: 28).width
    }

    private var drawsPicture: Bool {
        guard let target = model.target else { return false }
        return store.map { !EntityPictureLayout.isEmpty(target.type, picture: $0.picture(for: target.id)) } ?? false
    }

    var body: some View {
        Button { openURL(model.url) } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                if slot > 0 {
                    Group {
                        if let target = model.target, drawsPicture {
                            EntityPicture(id: target.id, name: target.name, type: target.type, size: 28)
                        }
                    }
                    .frame(width: CicadaTheme.scaled(slot), height: CicadaTheme.scaled(28), alignment: .leading)
                    .accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(model.title)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let meta = model.meta {
                        Text(meta)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            .pageCard(hovering: hovering || focused)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.return) {
            openURL(model.url)
            return .handled
        }
        .help(Copy.Pages.openPage(model.title))
        .accessibilityElement(children: .combine)
        .accessibilityLabel([model.title, model.meta].compactMap { $0 }.joined(separator: ", "))
        .accessibilityHint(Copy.Pages.opensPage)
        .accessibilityAddTraits(.isLink)
    }
}

/// One line of References: the source's mark, who and where and what it is called, its day. A card, not a numbered row.
struct ReferenceCard: View {
    let row: PageWords.ReferenceRow

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            RunSourceMarks.markView(row.markKey, size: CicadaTheme.scaled(20))
                .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
                .accessibilityHidden(true)
            Text(line)
                .font(CicadaTheme.metaFont)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let when = row.when {
                Text(when).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    .fixedSize()
            }
        }
        .pageCard()
        .accessibilityElement(children: .combine)
    }

    /// "You, in ChatGPT · <title>": who and where in the secondary ink, the title in the primary.
    private var line: AttributedString {
        var who = AttributedString(row.who)
        who.foregroundColor = CicadaTheme.textSecondary
        var gone = AttributedString(row.removed ? " · \(Copy.Provenance.sourceRemoved)" : "")
        gone.foregroundColor = CicadaTheme.textTertiary   // G104 slice 3: quiet, after the title, never in its place
        var edited = AttributedString(row.edited.map { " · \($0)" } ?? "")   // G244: the same quiet place
        edited.foregroundColor = CicadaTheme.textTertiary
        guard let title = row.title else { return who + gone + edited }
        var rest = AttributedString(" · \(title)")
        rest.foregroundColor = CicadaTheme.textPrimary
        return who + rest + gone + edited
    }
}
