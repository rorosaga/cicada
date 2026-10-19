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

    /// What a copy from the row's context menu takes, named for the row's second line when a person can use the name:
    /// a page's site and path, "3 tab links", a file's name. A conversation's session id and the episode id are
    /// machine ids — `nil` here, so they stay off the row (owner 2026-10-19, DR-54) and live in `.help` and the menu.
    static func target(kind: String?, value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        switch kind {
        case "link":
            guard let url = URL(string: value), let host = url.host() else { return value }
            let path = url.path()
            return path.isEmpty || path == "/" ? host : host + path
        case "links":
            let count = value.split(separator: "\n").count
            return "\(count) tab links"
        case "path":
            return (value as NSString).lastPathComponent
        default:
            return nil
        }
    }

    /// The second line: the copy target a person can read, and "read" once Sleep read it — the fact the status dot
    /// carried. `nil` (no line) when neither applies.
    static func meta(target: String?, processed: Bool) -> String? {
        switch (target, processed) {
        case let (t?, true): "\(t) · read"
        case let (t?, false): t
        case (nil, true): "read"
        case (nil, false): nil
        }
    }

    /// The tooltip: what a click does, when the episode arrived and, for a conversation that kept going, when it
    /// last changed — then the episode's id (DR-54: reachable in `.help`, never on the row).
    static func help(kind: String?, timestamp: String, changedAt: String?, id: String) -> String {
        var parts = [Copy.SleepDetailsWords.openHint(kind), "Added \(time(timestamp))"]
        if let changedAt, !changedAt.isEmpty, changedAt != timestamp { parts.append("Updated \(time(changedAt))") }
        parts.append(Copy.SleepDetailsWords.episodeIdHelp(id))
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

/// What a row does (owner 2026-10-19), pure so `SleepDetailsTests` holds it: a click opens the stored episode in the
/// Reader (`GET /episodes/{id}/text`); copying what Sleep would read is the context menu's. With no Reader in the
/// environment (a preview, a test host) a click copies instead, so the row never does nothing.
enum EpisodeRowAction: Equatable {
    case open(ReaderTarget)
    case copy(String)

    static func primary(_ item: EpisodeQueueItem, readerAvailable: Bool) -> EpisodeRowAction {
        readerAvailable ? .open(reader(item)) : .copy(copyValue(item))
    }

    static func reader(_ item: EpisodeQueueItem) -> ReaderTarget {
        ReaderTarget(episode: item.id, knownTitle: item.title)
    }

    /// What the context menu copies: the backend's `copyValue`, else the episode id.
    static func copyValue(_ item: EpisodeQueueItem) -> String {
        guard let value = item.copyValue, !value.isEmpty else { return item.id }
        return value
    }

    /// The copy target's kind, `nil` when the backend named none (the episode id is copied).
    static func copyKind(_ item: EpisodeQueueItem) -> String? {
        guard let value = item.copyValue, !value.isEmpty else { return nil }
        return item.copyKind
    }
}

/// One queued or read episode (DR-48): the source's real mark (DR-52), the title, a meta line and a
/// two-line preview. A row carries one glyph, so the status dot left — "read" is in the meta line.
/// The source pill left too: the origin row above it and the spine's header already name the source
/// (DR-38), and a raw origin slug never sits at body weight (DR-54). Hover is a fill, never a lift (R-HS15).
///
/// Owner 2026-10-19 (supersedes the 2026-10-05 copy-on-click): the whole row is one button that opens the stored
/// conversation — or the saved page, tab group or file text — in the Reader. Copying what Sleep would read (a
/// conversation's id, a page's link, a tab group's links, a file's path) moved to the context menu and a named
/// VoiceOver action, with its brief toast; the raw ids left the meta line for `.help` (DR-54). The row ends with its
/// day (a conversation's last change, else when it was added).
///
/// Extracted out of `SleepView.swift` (G125 Task 6, R11) — `StudyListCard`'s per-origin disclosure
/// and the room's `SpinePopover` both render it, so the spine popover draws the same row.
struct EpisodeRow: View {
    let item: EpisodeQueueItem
    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var hovering = false

    private var kind: String? { EpisodeRowAction.copyKind(item) }

    var body: some View {
        Button(action: activate) {
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                OriginMark(origin: item.origin, size: CicadaTheme.scaled(14))
                    .padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(item.title ?? Copy.SleepDetailsWords.untitled)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(item.processed ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                    if let meta = EpisodeRowText.meta(target: EpisodeRowText.target(kind: kind, value: item.copyValue),
                                                      processed: item.processed) {
                        Text(meta)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
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
        .help(EpisodeRowText.help(kind: kind, timestamp: item.timestamp, changedAt: item.changedAt, id: item.id))
        .contextMenu {
            Button(Copy.SleepDetailsWords.copyAction(kind), action: copy)
        }
        .accessibilityHint(Copy.SleepDetailsWords.openHint(kind))
        .accessibilityAction(named: Text(Copy.SleepDetailsWords.copyAction(kind)), copy)
    }

    private func activate() {
        switch EpisodeRowAction.primary(item, readerAvailable: reader != nil) {
        case .open(let target): reader?.open(target)
        case .copy: copy()
        }
    }

    /// The person caused it, so the words are announced as well as shown.
    private func copy() {
        AppPasteboard.copy(EpisodeRowAction.copyValue(item))
        let message = Copy.SleepDetailsWords.copied(kind)
        store?.flash(message)
        AccessibilityNotification.Announcement(message).post()
    }
}
