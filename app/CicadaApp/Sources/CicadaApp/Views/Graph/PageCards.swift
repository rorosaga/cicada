import SwiftUI

// MARK: - Cards on an entity page (owner 2026-11-23, DESIGN_RULES §9: "i would copy more the ui of superwhisper look")
//
// Related and References rows are soft rounded cards on a slightly lighter fill with a hairline ring (DR-9, DR-12), each
// leading with its mark or picture, then its title and a quiet meta line. This page only: Key Facts stays a plain list
// (its chips and source clusters carry it), and no other page changes.

/// The one card surface of an entity page: the app's one soft card (`SoftCardChrome`, `Theme/SoftCard.swift`) on the
/// page's ground, snug for a one-line title and its meta line. Hover takes the row-hover fill where the card is a control.
struct PageCardSurface: ViewModifier {
    var hovering = false

    func body(content: Content) -> some View {
        content.softCard(inset: .snug, hovering: hovering, fillsWidth: true)
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
            SourceMarkTile(key: row.markKey, size: CicadaTheme.scaled(20))
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

// MARK: - A source's mark on this page (owner 2026-11-23)

/// Which sources draw a mark on an entity page. A real mark or none, never a generic glyph: a web lookup and another
/// page of the bank have their own (the globe and the page glyph, explicit marks the Sleep page's cluster wears too);
/// every other place is an origin that draws only when the app has its real mark — the installed app's icon or a bundled
/// logo (`OriginMark.hasRealMark`). Anything else (an unknown channel, a folder) draws nothing and its row's words
/// ("You, in <place>") carry it.
enum PageSourceMark {
    nonisolated(unsafe) private static var memo: [String: Bool] = [:]

    /// Called from a view's body, so on the main actor (installed-app icons are looked up there).
    static func isDrawn(_ key: String) -> Bool {
        if key == "web" || key == "page" { return true }
        return MainActor.assumeIsolated {
            if let held = memo[key] { return held }
            let real = key != SourceClusterModel.unknown && OriginMark.hasRealMark(key)
            memo[key] = real
            return real
        }
    }
}

/// One source's mark on a small rounded tile (the neutral `bgBadge` one the Sleep page's marks sit on), scaled to the
/// size asked: 14 pt on the text line in a cluster, 20 pt in a References card or a popover row. A source with no real
/// mark draws an empty slot of the same size.
struct SourceMarkTile: View {
    let key: String
    let size: CGFloat

    var body: some View {
        if PageSourceMark.isDrawn(key) {
            let inner = (size * 0.74).rounded()
            ZStack {
                switch key {
                case "web":
                    Image(systemName: "globe").font(CicadaTheme.font(size: size * 0.6, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                case "page":
                    Image(systemName: "doc.text").font(CicadaTheme.font(size: size * 0.6, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                default:
                    OriginMark(origin: key, size: inner)
                }
            }
            .frame(width: size, height: size)
            .background(CicadaTheme.shape(max(CicadaTheme.scaled(4), size * 0.26)).fill(CicadaTheme.bgBadge))
            .accessibilityHidden(true)
        } else {
            Color.clear.frame(width: size, height: size)
        }
    }
}
