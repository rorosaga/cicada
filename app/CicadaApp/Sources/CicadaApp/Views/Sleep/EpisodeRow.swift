import SwiftUI

/// A queued or read episode's words, pure (`SleepDetailsTests`).
enum EpisodeRowText {
    /// "Nov 3, 2026 14:02" — the year kept (a queue can span years after a bulk import); "—" for an
    /// empty stamp; the raw start of anything that does not parse, rather than a blank.
    static func time(_ raw: String) -> String {
        guard !raw.isEmpty else { return "—" }
        guard let date = parse(raw) else { return String(raw.prefix(16)) }
        return display.string(from: date)
    }

    /// The day a row ends with (owner 2026-10-05): "Oct 3", with the year only when it is not this year;
    /// empty for a stamp that does not parse, so the row never shows a raw string at its edge.
    static func day(_ raw: String, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard let date = parse(raw) else { return "" }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        return (sameYear ? dayFormat : dayYearFormat).string(from: date)
    }

    /// What a click copies, named for the row's second line: a page's site and path, "Conversation 0f3c1a2b",
    /// "3 tab links", a file's name, else the episode id.
    static func target(kind: String?, value: String?, id: String) -> String {
        guard let value, !value.isEmpty else { return id }
        switch kind {
        case "link":
            guard let url = URL(string: value), let host = url.host() else { return value }
            let path = url.path()
            return path.isEmpty || path == "/" ? host : host + path
        case "links":
            let count = value.split(separator: "\n").count
            return "\(count) tab links"
        case "conversation":
            return "Conversation \(value.prefix(8))"
        case "path":
            return (value as NSString).lastPathComponent
        default:
            return value
        }
    }

    /// The second line: what a click copies, and "read" once Sleep read it — the fact the status dot carried.
    static func meta(target: String, processed: Bool) -> String {
        processed ? "\(target) · read" : target
    }

    /// The tooltip: what a click does, when the episode arrived and, for a conversation that kept going, when
    /// it last changed.
    static func help(kind: String?, timestamp: String, changedAt: String?) -> String {
        var parts = [Copy.SleepDetailsWords.copyHint(kind), "Added \(time(timestamp))"]
        if let changedAt, !changedAt.isEmpty, changedAt != timestamp { parts.append("Updated \(time(changedAt))") }
        return parts.joined(separator: " · ")
    }

    private static func parse(_ raw: String) -> Date? {
        guard !raw.isEmpty else { return nil }
        // Accept both ISO-8601 shapes (with and without fractional seconds).
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: raw)
    }

    private static let display: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MMM d, yyyy HH:mm"
        return f
    }()
    private static let dayFormat: DateFormatter = {
        let f = DateFormatter()
        f.setLocalizedDateFormatFromTemplate("MMM d")
        return f
    }()
    private static let dayYearFormat: DateFormatter = {
        let f = DateFormatter()
        f.setLocalizedDateFormatFromTemplate("MMM d yyyy")
        return f
    }()
}

/// One queued or read episode (DR-48): the source's real mark (DR-52), the title, a meta line and a
/// two-line preview. A row carries one glyph, so the status dot left — "read" is in the meta line.
/// The source pill left too: the origin row above it and the spine's header already name the source
/// (DR-38), and a raw origin slug never sits at body weight (DR-54). Hover is a fill, never a lift (R-HS15).
///
/// Owner 2026-10-05: the whole row is one button that copies what Sleep would read — a conversation's id, a
/// page's link, a tab group's links, a file's path — and says so in a brief toast; the meta line names that
/// target, and the row ends with its day (a conversation's last change, else when it was added).
///
/// Extracted out of `SleepView.swift` (G125 Task 6, R11) — `StudyListCard`'s per-origin disclosure
/// and the room's `SpinePopover` both render it, so the spine popover draws the same row.
struct EpisodeRow: View {
    let item: EpisodeQueueItem
    @Environment(Store.self) private var store: Store?
    @State private var hovering = false

    private var kind: String? { item.copyValue == nil ? nil : item.copyKind }

    var body: some View {
        Button(action: copy) {
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                OriginMark(origin: item.origin, size: CicadaTheme.scaled(14))
                    .padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(item.title ?? Copy.SleepDetailsWords.untitled)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(item.processed ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                    Text(EpisodeRowText.meta(target: EpisodeRowText.target(kind: kind, value: item.copyValue, id: item.id),
                                             processed: item.processed))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    if !item.preview.isEmpty {
                        Text(item.preview)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(EpisodeRowText.day(item.changedAt ?? item.timestamp))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
                    .padding(.top, CicadaTheme.scaled(2))
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
        .help(EpisodeRowText.help(kind: kind, timestamp: item.timestamp, changedAt: item.changedAt))
        .accessibilityHint(Copy.SleepDetailsWords.copyHint(kind))
    }

    /// The person caused it, so the words are announced as well as shown.
    private func copy() {
        AppPasteboard.copy(item.copyValue ?? item.id)
        let message = Copy.SleepDetailsWords.copied(kind)
        store?.flash(message)
        AccessibilityNotification.Announcement(message).post()
    }
}
