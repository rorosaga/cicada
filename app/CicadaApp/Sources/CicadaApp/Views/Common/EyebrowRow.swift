import AppKit
import SwiftUI

/// The list page's header (DR-25): no page-title band — a name on the left ("Inbox" in 20 semibold
/// `textPrimary`, ROR-118, then its " · 6 pending" in `metaFont` `textTertiary`, tabular) and the page's text tabs on the right, in one
/// row at least 28 pt tall, 20 pt below the titlebar. The old subtitle moves into the `?`
/// popover and the empty state. Built here; each list page adopts it in its DS track (R-DS27).
struct EyebrowRow<Trailing: View>: View {
    static var topPadding: CGFloat { 20 }
    static var minHeight: CGFloat { 32 }

    /// How far the title's capital letters sit below its line box's top, from the face's own metrics: a bare row pulls
    /// up by it, so the first ink of the title is the top of the block it opens, not a few points under it.
    static var capInset: CGFloat {
        let face = NSFont.systemFont(ofSize: CicadaTheme.scaled(20), weight: .semibold)
        return max(0, (face.ascender - face.capHeight).rounded(.down))
    }

    let eyebrow: String
    /// 40 pt with nothing open (the list alone), 24 pt once columns open (§5.3).
    var horizontalPadding: CGFloat = CicadaTheme.spacingGutter
    /// True when the trailing content adapts to the width it is given (`OverflowTextTabs`): the eyebrow keeps its
    /// words and the trailing side is offered all the rest, so `ViewThatFits` measures against the real space. In
    /// the default HStack the eyebrow and the tabs share the shortfall, and a tab label truncated ("Conf…").
    var adaptiveTrailing = false
    /// The title alone, with none of the row's own paddings or minimum height (its first line's top is the block's top): a page that sets it inside a block it lays out (Sleep's
    /// corner, ROR-118) owns the edges.
    var bare = false
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            // ROR-118 — the page's name leads in `pageNameFont` / `textPrimary`; what follows " · " (its counts, a
            // status) stays `metaFont` / `textTertiary` beside it, so the metadata sits next to what it describes.
            let parts = Eyebrow.split(eyebrow)
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(parts.name)
                    .font(CicadaTheme.pageNameFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let rest = parts.rest {
                    Text(rest)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .monospacedDigit()
            .lineLimit(1)
            .layoutPriority(adaptiveTrailing ? 1 : 0)
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isHeader)
            if adaptiveTrailing {
                trailing().frame(maxWidth: .infinity, alignment: .trailing)
            } else {
                Spacer(minLength: CicadaTheme.spacingSM)
                trailing()
            }
        }
        .frame(minHeight: bare ? nil : CicadaTheme.scaled(Self.minHeight))
        .padding(.top, bare ? -Self.capInset : CicadaTheme.scaled(Self.topPadding))
        .padding(.horizontal, bare ? 0 : horizontalPadding)
        .padding(.bottom, bare ? 0 : CicadaTheme.spacingMD)
    }
}

extension EyebrowRow where Trailing == EmptyView {
    init(eyebrow: String, horizontalPadding: CGFloat = CicadaTheme.spacingGutter) {
        self.init(eyebrow: eyebrow, horizontalPadding: horizontalPadding, trailing: { EmptyView() })
    }
}

/// "Inbox · 1 of 6 · Conflict" — the eyebrow's grammar: parts joined by a middle dot, an
/// empty part dropped so a page with nothing pending never reads "Clusters · ".
enum Eyebrow {
    /// The page's name and what follows it ("Projects · still indexing" → "Projects", "still indexing").
    static func split(_ text: String) -> (name: String, rest: String?) {
        guard let range = text.range(of: " · ") else { return (text, nil) }
        let rest = String(text[range.upperBound...])
        return (String(text[..<range.lowerBound]), rest.isEmpty ? nil : rest)
    }

    static func text(_ parts: String...) -> String {
        parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
