import SwiftUI

/// A queued or read episode's words, pure (`SleepDetailsTests`).
enum EpisodeRowText {
    /// "Nov 3, 2026 14:02" — the year kept (a queue can span years after a bulk import); "—" for an
    /// empty stamp; the raw start of anything that does not parse, rather than a blank.
    static func time(_ raw: String) -> String {
        guard !raw.isEmpty else { return "—" }
        // Accept both ISO-8601 shapes (with and without fractional seconds).
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) { return display.string(from: date) }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) { return display.string(from: date) }
        return String(raw.prefix(16))
    }

    /// The meta line: the time, and "read" once Sleep read it — the fact the status dot carried.
    static func meta(timestamp: String, processed: Bool) -> String {
        processed ? "\(time(timestamp)) · read" : time(timestamp)
    }

    private static let display: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MMM d, yyyy HH:mm"
        return f
    }()
}

/// One queued or read episode (DR-48): the source's real mark (DR-52), the title, a meta line and a
/// two-line preview. A row carries one glyph, so the status dot left — "read" is in the meta line.
/// The source pill left too: the origin row above it and the spine's header already name the source
/// (DR-38), and a raw origin slug never sits at body weight (DR-54); the id is on hover. Hover is a
/// fill, never a lift (R-HS15).
///
/// Extracted out of `SleepView.swift` (G125 Task 6, R11) — `StudyListCard`'s per-origin disclosure
/// and the room's `SpinePopover` both render it, so the spine popover draws the same row.
struct EpisodeRow: View {
    let item: EpisodeQueueItem
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            OriginMark(origin: item.origin, size: CicadaTheme.scaled(14))
                .padding(.top, CicadaTheme.scaled(2))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(item.title ?? Copy.SleepDetailsWords.untitled)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(item.processed ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                Text(EpisodeRowText.meta(timestamp: item.timestamp, processed: item.processed))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                if !item.preview.isEmpty {
                    Text(item.preview)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
        .help(item.id)
    }
}
