import SwiftUI

/// Up to `limit` of an origin's queued episodes, newest first, and how many
/// more there are (Track Z §7.1) — the same order `episodesForOrigin` gives
/// the Details row, so the popover and the row can never disagree about
/// which episodes are the newest.
func spinePopoverRows(origin: String, in episodes: [EpisodeQueueItem], limit: Int = 6)
    -> (rows: [EpisodeQueueItem], more: Int) {
    let all = episodesForOrigin(origin, in: episodes)
    return (Array(all.prefix(limit)), max(0, all.count - limit))
}

/// A spine's popover (§7.1): the source's mark, name and state in words, the
/// oldest age, its newest episodes, then the two ways further — Details for
/// the rest, Sources for the source's own page (hidden when no source owns
/// the origin, never guessed — R-A14).
struct SpinePopover: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    let row: StudyRow
    let episodes: [EpisodeQueueItem]
    let onOpenDetails: () -> Void

    var body: some View {
        let shown = spinePopoverRows(origin: row.origin, in: episodes)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: row.origin, size: 18)
                Text(row.label)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: 0)
                Text(queueRowWords(queueRowState(row)))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if let age = row.oldestAge {
                Text("oldest \(age)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(shown.rows) { EpisodeRow(item: $0) }
            HStack {
                if shown.more > 0 {
                    Button(Copy.moreInDetails(shown.more), action: onOpenDetails)
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                }
                Spacer(minLength: 0)
                if let source = SourceOverview.owning(origin: row.origin, in: store.sourcesOverview.value ?? []) {
                    Button(Copy.openInSources) { router.routeToSourceDetail(source.id) }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.accent)
                }
            }
            .font(CicadaTheme.captionFont)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360)
        .background(CicadaTheme.surface)
    }
}
