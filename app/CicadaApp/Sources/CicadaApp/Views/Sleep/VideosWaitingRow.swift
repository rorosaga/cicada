import SwiftUI

/// G162 (the VideoSleepWaiting board) — one read-only row in Details › What's waiting: a play glyph, "Videos", the one
/// queue wording ("4 queued · 1 picked up by an agent · 1 couldn't be done", a clause omitted at zero) and a trailing
/// *Choose videos ›* that opens the Feed's picker. It starts nothing (R-VU4: a watch run is the person's own agent's
/// work, never a Sleep cycle, and the page's one cycle control is untouched), never says "being watched"
/// (R-VU9), and is drawn only while something is in the queue. Its own file, so the Sleep page's call site is a few
/// lines (the Sleep v5 branch owns the section).
struct VideosWaitingRow: View {
    @Environment(VideoStateCache.self) private var cache: VideoStateCache?
    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let line = VideosWaitingRowText.line(cache?.summary) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "play.rectangle")
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .frame(width: CicadaTheme.scaled(12))
                        .accessibilityHidden(true)
                    Text(Copy.Videos.sleepRowTitle)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    TextButton(title: Copy.Videos.sleepRowLink, help: Copy.Videos.sleepRowLinkHelp, inline: true) {
                        router?.routeToVideos(choose: true)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
                .background(hovering ? CicadaTheme.bgHover : Color.clear, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .onHover { hovering = $0 }
                .accessibilityElement(children: .combine)
            }
        }
        // The counts only (no per-video rows); a 304 costs nothing.
        .task { await cache?.refreshSummary() }
    }
}

enum VideosWaitingRowText {
    /// The row's line, or nil when nothing is in the queue (the row is not drawn then).
    static func line(_ summary: VideoSummary?) -> String? { VideoQueueLine.text(summary) }
}
