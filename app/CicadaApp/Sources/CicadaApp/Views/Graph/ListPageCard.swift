import SwiftUI

/// G246 (ruling 81, owner 2026-11-24: "i want to somehow see saved things somewhere even if i haven't referred to them
/// yet") — the page of one list of saved posts, or of one folder on a site that files saves into them.
///
/// It says what the list is in the one line the page itself holds, under the site's real mark (DR-52), then how many
/// are saved there, the day of the newest and when this Mac last read it (DR-38: each said once); for a folder the
/// person gave a reason to, that reason in their own words — here and nowhere else. Then the **five newest items as the
/// same cards the Sources page uses** (DR-37) and a plain "All N" that opens the whole list in the column's place
/// (DR-81; Esc returns). Nothing on the page is a copy: the count, the newest day and the cards come from the saves each
/// time the page opens (`blocks.list` and the items route), so the page cannot be out of date. A list with nothing in it
/// draws nothing at all (DR-81).
///
/// Order is the server's (DR-78): the page's block arrives with the card (`GET /entities/{id}`'s `blocks`), the app
/// invents none. No picture and no glyph beyond the mark (CLAUDE.md pictures); both appearances are first-class (DR-71);
/// nothing here animates (DR-60, DR-61).
struct ListPageCard: View {
    let entity: Entity
    let list: PageBlocks.ListBlock
    var today: ISODay = .today()

    @State private var showsAll = false

    /// The line the page itself holds about what the list is: its prose, trimmed ("Posts you bookmarked on X.").
    static func about(_ markdown: String) -> String {
        markdown.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty && !$0.hasPrefix("#") } ?? ""
    }

    /// "142 saved · newest Tuesday · last read 2 days ago" — every part optional but the count (a list read by another Mac,
    /// or never by this one, says no read). A day the list has not reached is never invented.
    static func stats(_ list: PageBlocks.ListBlock, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [Copy.Lists.saved(list.count)]
        if let day = ISODay(list.newest) {
            parts.append(Copy.Lists.newestOn(said(RelativeDay.phrase(day, today: today, locale: locale))))
        }
        if let read = ISODay(list.lastReadAt) {
            parts.append(Copy.Lists.lastReadOn(said(RelativeDay.phrase(read, today: today, locale: locale))))
        }
        return parts.joined(separator: " · ")
    }

    /// "Today" reads "today" inside a line; a weekday or a date keeps its capital.
    private static func said(_ phrase: String) -> String {
        ["Today", "Yesterday", "Tomorrow"].contains(phrase) ? phrase.lowercased() : phrase
    }

    /// A list that holds nothing is not drawn (DR-81): the count is the server's, read now.
    static func isDrawn(_ list: PageBlocks.ListBlock) -> Bool { list.count > 0 }

    var body: some View {
        if Self.isDrawn(list) {
            if showsAll { whole } else { overview }
        }
    }

    // MARK: - The five newest, then "All N"

    private var overview: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    if !list.source.isEmpty { OriginMark(origin: list.source, size: CicadaTheme.scaled(16)) }
                    Text(Self.about(entity.markdownContent))
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .accessibilityIdentifier("list-page-about")
                }
                Text(Self.stats(list, today: today))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityIdentifier("list-page-stats")
                if let why = list.why, !why.text.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        SectionLabel(Copy.Lists.whyThisFolder)
                        Text(why.text)
                            .font(CicadaTheme.detailBodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("list-page-why")
                    }
                    .padding(.top, CicadaTheme.spacingXS)
                }
            }
            SourceStreamCards(key: list.listKey, cap: Self.cap, omittingList: list.label) { _ in
                showsAll = true
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// DR-81: an open section holds at most five rows.
    static let cap = 5

    // MARK: - The whole list, in the column's place

    private var whole: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SourceDrillHead(source: entity.name, title: nil) { Instant.run { showsAll = false } }
            SourceStreamCards(key: list.listKey, cap: nil, omittingList: list.label) { _ in }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
