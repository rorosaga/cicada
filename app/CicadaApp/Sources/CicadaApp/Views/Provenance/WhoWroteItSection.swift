import SwiftUI

/// "Who wrote it" (G198, owner ruling 2026-10-14: "who changed what and at what time, the same as a doc in git"):
/// inside "Where this comes from", one row per part of the page's text — who last changed its lines, how many, when,
/// and for an agent's edit the reason it gave (and "accepted by you" when the person applied it from the inbox).
///
/// Read from `GET /entities/{id}/blame` when "Where this comes from" shows (`PageSourcesSection` loads it through
/// `ProvenanceCache` — never a Store domain, R-PB11); a re-open draws the held answer at once and asks again. A
/// backend without the route, or a page with no history, draws nothing (R10). Quiet by design: section label (DR-20/DR-47), the shared author marks (DR-52), meta
/// type, the first four parts with "Show all" (DR-39), no card of its own (DR-37).
struct WhoWroteItSection: View {
    let blame: PageBlame

    @State private var showAll = false

    static let visibleSections = 4

    /// Whether there is anything to draw: the parent leaves the section out otherwise (no empty gap).
    static func shows(_ blame: PageBlame?) -> Bool {
        blame.map { !PageBlameWords.sections($0).isEmpty } ?? false
    }

    var body: some View { content(blame) }

    private func content(_ blame: PageBlame) -> some View {
        let sections = PageBlameWords.sections(blame)
        let shown = showAll ? sections : Array(sections.prefix(Self.visibleSections))
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.PageEdits.sectionLabel)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(shown) { section in sectionRow(section, in: blame) }
            }
            if sections.count > Self.visibleSections {
                TextButton(title: showAll ? Copy.Inbox.showFewer : Copy.Inbox.showAll(sections.count)) {
                    showAll.toggle()
                }
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
        .help(Copy.PageEdits.help)
    }

    private func sectionRow(_ section: PageBlameSection, in blame: PageBlame) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            Text(PageBlameWords.title(section))
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            ForEach(PageBlameWords.visible(section)) { c in contributorLine(c, in: blame) }
            if let more = PageBlameWords.more(section) {
                Text(more)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.leading, CicadaTheme.scaled(22))
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func contributorLine(_ c: PageBlameContributor, in blame: PageBlame) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ContributorAvatar(author: c.author,
                                  kind: ContributorIdentity.kind(author: c.author, serverKind: c.authorKind),
                                  provider: c.authorProvider, size: CicadaTheme.scaled(14))
                Text(PageBlameWords.name(c))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(PageBlameWords.detail(c))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            if let reason = PageBlameWords.reason(c, in: blame) {
                Text(reason)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, CicadaTheme.scaled(22))
            }
        }
    }
}
