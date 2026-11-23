import Foundation

extension PageInline {
    /// Bench and test switch: `false` draws every line as one `Text`, the way a page was drawn before chips. Never
    /// changed by the app.
    nonisolated(unsafe) static var flowEnabled = true
}

/// A Related list item as a card (owner 2026-11-23, the Superwhisper look on this page only): the page it names, its
/// picture, and under its name the quiet words that say how it is related ("works at"). A rolled-up line ("people: 120
/// pages — latest …") names no page and stays a plain bullet.
struct RelatedCardModel: Equatable {
    let target: PageLinkTarget?
    /// The page's own name when the link resolved, else the words it was written under.
    let title: String
    /// What the line says of the link, after the name: "works at", never the dash that joined it.
    let meta: String?
    /// The page's chip URL when resolved, else the link as written (today's click, G227).
    let url: URL

    /// The model for a list item whose first piece is a link to a page, else nil.
    static func make(_ text: AttributedString, resolve: (String) -> PageLinkTarget?) -> RelatedCardModel? {
        guard let first = text.runs.first(where: { !String(text[$0.range].characters).allSatisfy(\.isWhitespace) }),
              let url = first.link, let ref = PageInline.entityRef(url) else { return nil }
        var end = first.range.upperBound
        for run in text.runs where run.range.lowerBound >= first.range.upperBound {
            guard run.link == url else { break }
            end = run.range.upperBound
        }
        let written = String(text[first.range.lowerBound..<end].characters)
        let rest = String(text[end...].characters)
            .trimmingCharacters(in: CharacterSet(charactersIn: "—–-:").union(.whitespacesAndNewlines))
        let target = resolve(ref)
        return RelatedCardModel(target: target, title: target?.name ?? written, meta: rest.isEmpty ? nil : rest,
                                url: target.flatMap { PageInline.pageURL($0.id) } ?? url)
    }

    /// The article's Related items, by row id: every list item under a `## Related` heading that names a page.
    static func rows(in article: WikiArticle, resolve: (String) -> PageLinkTarget?) -> [Int: RelatedCardModel] {
        var inRelated = false
        var out: [Int: RelatedCardModel] = [:]
        for row in article.rows {
            switch row.kind {
            case .heading:
                inRelated = WikiPageView.isSection(row, "Related")
            case .item where inRelated:
                if let card = make(row.text, resolve: resolve) { out[row.id] = card }
            default:
                break
            }
        }
        return out
    }
}
