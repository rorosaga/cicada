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

    /// The tooltip: what a click does, when the episode arrived and, for a conversation that kept going, when it
    /// last changed — then the episode's id (DR-54: reachable in `.help`, never on the row).
    static func help(kind: String?, timestamp: String, changedAt: String?, id: String) -> String {
        var parts = [Copy.SleepDetailsWords.openHint(kind), "Added \(time(timestamp))"]
        if let changedAt, !changedAt.isEmpty, changedAt != timestamp { parts.append("Updated \(time(changedAt))") }
        parts.append(Copy.SleepDetailsWords.episodeIdHelp(id))
        return parts.joined(separator: " · ")
    }

    /// A card's footer after its mark: where it is (a page's site and path, "3 tab links", a file's name), how long
    /// ago it last changed, and "read" once Sleep read it. The source's name is never repeated: the source card above
    /// names it once (DR-38), and the mark carries it at a glance.
    static func footer(_ item: EpisodeQueueItem, target: String?, now: Date = Date()) -> [String] {
        var parts = target.map { [$0] } ?? []
        if let date = parse(item.changedAt ?? item.timestamp) ?? parse(item.timestamp) {
            parts.append(Copy.OriginCard.ago(date, now: now))
        }
        if item.processed { parts.append("read") }
        return parts
    }

    /// What VoiceOver reads for a card: the title, then the footer's words.
    static func cardLabel(_ item: EpisodeQueueItem, target: String?, now: Date = Date()) -> String {
        ([item.title ?? Copy.SleepDetailsWords.untitled] + footer(item, target: target, now: now)).joined(separator: ", ")
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

/// One queued or read episode, as a card of the `OriginCard` family (owner 2026-11-23: "a big card per source and
/// inside a card for individual things" on the Sleep page): the title, two lines of what it says, and under them
/// `[mark] where · 5d ago · read` — the glance the reason cards give. A waiting episode is `plain` (no accent: a queue
/// is not a history, DR-5 stands); one Sleep already read is `past`, faded until the pointer is on it.
///
/// Owner 2026-10-19 still holds: the whole card is one button that opens the stored conversation — or the saved page,
/// tab group or file text — in the Reader. The preview is the first 200 characters, so a card that expanded in place
/// would show one more line; the Reader shows all of it. Copying what Sleep would read stays in the context menu and a
/// named VoiceOver action; the raw ids stay in `.help` (DR-54). The footer's mark is a saved link's own site
/// (owner 2026-10-20), else the source's real mark (DR-52); the source card above already names the source (DR-38),
/// so the footer names only the page, tab group or file, when there is one.
///
/// `StudyListCard`'s source cards and the room's `SpinePopover` both render it.
struct EpisodeCard: View {
    let item: EpisodeQueueItem
    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var kind: String? { EpisodeRowAction.copyKind(item) }
    private var target: String? { EpisodeRowText.target(kind: kind, value: item.copyValue) }

    var body: some View {
        Button(action: activate) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                Text(item.title ?? Copy.SleepDetailsWords.untitled)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(item.processed ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                    .lineLimit(1)
                if !item.preview.isEmpty {
                    Text(item.preview)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                footer
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .originCardChrome(tone: item.processed ? .past : .plain, hovering: hovering)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .help(EpisodeRowText.help(kind: kind, timestamp: item.timestamp, changedAt: item.changedAt, id: item.id))
        .contextMenu {
            // Owner 2026-11-23: the original, where it lives — first, then the copy.
            if let opens = EpisodeOpen.target(item),
               let label = EpisodeOpen.label(opens, appName: EpisodeOpen.installedAppName) {
                Button(label) { openOriginal(opens) }
            }
            Button(Copy.SleepDetailsWords.copyAction(kind), action: copy)
        }
        .accessibilityLabel(EpisodeRowText.cardLabel(item, target: target))
        .accessibilityHint(Copy.SleepDetailsWords.openHint(kind))
        .accessibilityAction(named: Text(Copy.SleepDetailsWords.copyAction(kind)), copy)
        .accessibilityActions {
            if let opens = EpisodeOpen.target(item),
               let label = EpisodeOpen.label(opens, appName: EpisodeOpen.installedAppName) {
                Button(label) { openOriginal(opens) }
            }
        }
    }

    private var footer: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            mark
            ForEach(Array(EpisodeRowText.footer(item, target: target).enumerated()), id: \.offset) { index, part in
                if index > 0 { Text("·") }
                Text(part).monospacedDigit()
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Image(systemName: "arrow.up.right")
                .font(CicadaTheme.font(size: 9, weight: .semibold))
                .opacity(hovering ? 1 : 0)
                .accessibilityHidden(true)
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
        .lineLimit(1)
        .truncationMode(.middle)
    }

    /// Owner 2026-10-20 — a saved link waiting to be read wears its own site's mark (`SavedLinkMark`, asked by the
    /// episode's id until Sleep makes its page); the source it came from already heads the group above (DR-38). Every
    /// other episode — a conversation, a note, a file — keeps its source's real mark (DR-52).
    @ViewBuilder
    private var mark: some View {
        if let site = SavedLinkMarkModel.mark(item) {
            SavedLinkMark(mark: site, size: .inline)
        } else {
            OriginMark(origin: item.origin, size: CicadaTheme.scaled(16))
        }
    }

    private func activate() {
        switch EpisodeRowAction.primary(item, readerAvailable: reader != nil) {
        case .open(let target): reader?.open(target)
        case .copy: copy()
        }
    }

    /// The menu's "Open in …": runs on that click alone; a problem (or a resumed session's line) is said as a toast.
    private func openOriginal(_ target: EpisodeOpen.Target) {
        Task { @MainActor in
            guard let words = await EpisodeOpen.open(target) else { return }
            store?.flash(words)
            AccessibilityNotification.Announcement(words).post()
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
