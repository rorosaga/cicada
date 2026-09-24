import Foundation

/// Round 4 (T-Sources; the owner, 2026-09-24: "showing the last sync of apps that are connected and such is
/// massive") — one row for a source that keeps up: its mark, its name, what it brings in, what it is doing right now,
/// and when it last synced. Pure, so Sources, Integrations, Home's Getting started and phase B's onboarding say the
/// same words from the same facts (the R-S19 rule: one projection, many renderings).
struct SourceRowModel: Equatable, Identifiable {
    let id: String
    /// An `OriginIconography` key: `OriginMark` draws the installed app's icon, then the bundled PNG, then a symbol
    /// (DR-52, Track L).
    let origin: String
    let title: String
    /// What it reads, after the name ("Bookmarks · Reading List · Favorites"). One line (DR-59).
    var meta: String? = nil
    /// The second line: what came in ("2,104 bookmarks · Reading List 36").
    var line: String? = nil
    var status: SourceRowStatus = .idle
}

enum SourceRowStatus: Equatable {
    /// Nothing to say on the right (off, or not a syncing source — the accessory says what to do).
    case idle
    case notYet
    case syncing(detail: String?, fraction: Double?, cancellable: Bool)
    case synced(Date)
    /// A one-shot import — never "Last synced" (R-SR12).
    case imported(Date)
    case problem(String)

    var isSyncing: Bool { if case .syncing = self { return true }; return false }
}

enum SourceRowText {
    /// How often a row re-reads the clock (DR-58: relative words are computed when read, never stored).
    static let refreshInterval: TimeInterval = 30

    static func lastSynced(_ date: Date, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        guard now.timeIntervalSince(date) >= 60 else { return Copy.lastSyncedJustNow }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        formatter.dateTimeStyle = .numeric
        formatter.locale = locale
        return Copy.lastSynced(formatter.localizedString(for: date, relativeTo: now))
    }

    /// "Imported 18:12" today, "Imported Sep 20" before (the F-09 row's words).
    static func imported(_ date: Date, now: Date, locale: Locale = .autoupdatingCurrent,
                         timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = timeZone
        if calendar.isDate(date, inSameDayAs: now) {
            formatter.dateStyle = .none
            formatter.timeStyle = .short
        } else {
            formatter.setLocalizedDateFormatFromTemplate("MMMd")
        }
        return Copy.importedAt(formatter.string(from: date))
    }

    static func trailing(_ status: SourceRowStatus, now: Date, locale: Locale = .autoupdatingCurrent) -> String? {
        switch status {
        case .idle: nil
        case .notYet: Copy.notSyncedYet
        case .syncing: Copy.syncingNow
        case .synced(let date): lastSynced(date, now: now, locale: locale)
        case .imported(let date): imported(date, now: now, locale: locale)
        case .problem(let why): why
        }
    }

    /// A running sync's own words ("Reading 2 of 3 open groups") replace the count line while it runs.
    static func secondLine(_ model: SourceRowModel) -> String? {
        if case .syncing(let detail?, _, _) = model.status { return detail }
        return model.line
    }

    /// One precedence for every host: this app's run, another reader's light, a failure, then the persisted sync.
    static func status(channel: SourceChannel?, watch: BrowserWatchState?, run: SyncActivity.Run?) -> SourceRowStatus {
        if let run { return .syncing(detail: run.detail, fraction: run.fraction, cancellable: run.cancellable) }
        if watch == .syncing { return .syncing(detail: nil, fraction: nil, cancellable: false) }
        if watch == .blocked { return .problem(Copy.sourceNeedsAccess) }
        if let error = channel?.lastError, let clause = SourceLiveness.firstClause(of: error) { return .problem(clause) }
        if watch == .failed { return .problem(Copy.sourceSyncFailed) }
        guard let channel, channel.connected else { return .idle }
        // "Not synced yet" only for a source that syncs or polls: Files & links (`import`, no `last_sync` by design)
        // and a Telegram bot with no capture yet (`[]`) have nothing late to report, so they say nothing.
        guard let date = channel.lastSyncDate else {
            return channel.actions.contains("sync") || channel.actions.contains("poll") ? .notYet : .idle
        }
        return channel.actions == ["import"] ? .imported(date) : .synced(date)
    }

    /// "2,104 bookmarks · Reading List 36 · Favorites 12" — the count in the reader's locale, then the parts.
    static func countLine(_ channel: SourceChannel, locale: Locale = .autoupdatingCurrent) -> String? {
        var pieces: [String] = []
        if channel.connected, let phrase = ChannelDetailLine.countPhrase(channel, locale: locale) { pieces.append(phrase) }
        pieces += channel.parts.compactMap { ChannelPartsText.phrase($0, locale: locale) }
        return pieces.isEmpty ? nil : pieces.joined(separator: " · ")
    }

    static func accessibilityLabel(_ model: SourceRowModel, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        [model.title, secondLine(model), trailing(model.status, now: now, locale: locale)]
            .compactMap { $0 }.joined(separator: ". ")
    }
}

/// R-SR14 — the words for a channel's parts; the backend ships only keys and counts.
enum ChannelPartsText {
    static func phrase(_ part: ChannelPart, locale: Locale = .autoupdatingCurrent) -> String? {
        guard part.count > 0 else { return nil }
        switch part.key {
        case "reading-list": return Copy.readingListCount(part.count, locale: locale)
        case "favorites": return Copy.favoritesCount(part.count, locale: locale)
        case "tabs": return Copy.tabsCount(part.count, locale: locale)
        case "people": return Copy.matchedPeople(part.count, locale: locale)
        default: return nil
        }
    }
}
