import SwiftUI

/// G162 — the list column while the watch run is on: the picker's rows for the chosen tab (Not yet read · Queued ·
/// Read, disjoint, nothing pre-selected), or, in progress, the hand-off's members with their live words and no check.
struct VideoRunList: View {
    let model: VideoRunModel
    let rows: [VideoRow]
    let style: ColumnPlan.ListStyle
    let escape: () -> Void

    @Environment(VideoStateCache.self) private var cache

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                content
            }
            .padding(ListInsets.of(style == .hidden ? .triage : style))
        }
        .onExitCommand { escape() }
    }

    @ViewBuilder
    private var content: some View {
        if rows.isEmpty {
            message(cache.isGone ? Copy.Videos.noSavedVideos : (cache.state == nil ? Copy.Videos.readingVideos : Copy.Videos.noSavedVideos))
        } else if model.mode == .progress, let batch = cache.summary?.batch, batch.total > 0 {
            ForEach(VideoRunProgress.members(batch: batch, rows: rows)) { member in VideoRunListRow(member: member) }
        } else {
            let shown = VideoRunModel.rows(rows, in: model.tab)
            if shown.isEmpty {
                message(model.tab.emptyMessage)
            } else {
                ForEach(shown) { row in
                    VideoPickRow(row: row, isSelected: model.isSelected(row.id)) { model.toggle(row) }
                }
            }
        }
    }

    private func message(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.top, CicadaTheme.spacingSM)
    }
}

enum VideoRunLayout {
    /// The picker column (units): 400, so "Northwind Robotics · length unknown" fits (§9 2026-09-30).
    static let pickerWidth: CGFloat = 400
}
