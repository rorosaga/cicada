import Foundation

// G162 — the pure half of the video surfaces: what each state and queue entry is called, which buttons a video gets,
// the queue's one wording and the run's size words. Nothing here reaches for a clock, a view or the network, so every
// rule is a plain XCTest. Words come from `Copy.Videos` (provider-neutral); a name in a sentence is DATA.

/// One saved video as a screen draws it: the Feed's row joined to the server's state by `mediaEntityId|url`.
struct VideoRow: Identifiable, Equatable {
    var item: MediaFeedItem
    var state: VideoStateItem
    var id: String { item.id }

    /// `MediaFeedItem` is not `Equatable`; a row is the same row when its id and its server state are.
    static func == (lhs: VideoRow, rhs: VideoRow) -> Bool {
        lhs.item.id == rhs.item.id && lhs.item.durationS == rhs.item.durationS && lhs.state == rhs.state
    }
}

enum VideoWords {
    /// The Tag over the block: what Cicada holds for this video. `unknown` (a state a newer backend invented) says nothing.
    static func stateTag(_ state: VideoWatchState) -> String? {
        switch state {
        case .none: Copy.Videos.stateNone
        case .transcript: Copy.Videos.stateTranscript
        case .watched: Copy.Videos.stateWatched
        case .watchedAndTranscript: Copy.Videos.stateBoth
        case .recorded: Copy.Videos.stateRecorded
        case .unknown: nil
        }
    }

    /// The row's trailing word: a queue word wins over the state word ("Queued", "Picked up", "Couldn't do"), and a video
    /// with nothing shows no word at all.
    static func rowWord(_ state: VideoStateItem?) -> String? {
        guard let state else { return nil }
        switch state.queueState {
        case .queued?: return Copy.Videos.rowQueued
        case .claimed?: return Copy.Videos.rowPickedUp
        case .failed?: return Copy.Videos.rowCouldntDo
        case nil: break
        }
        switch state.state {
        case .transcript: return Copy.Videos.rowTranscript
        case .watched: return Copy.Videos.rowWatched
        case .watchedAndTranscript: return Copy.Videos.rowBoth
        case .recorded: return Copy.Videos.rowRecorded
        case .none, .unknown: return nil
        }
    }

    /// "channel · site · length · saved Sep 29" — no "Video ·" (the tab already says so), a part omitted when the page
    /// does not carry it (R17: no length is no length, never an estimate).
    static func detailLine(_ item: MediaFeedItem, locale: Locale = .autoupdatingCurrent,
                           timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if let channel = clean(item.channel) { parts.append(channel) }
        if let site = clean(item.site) { parts.append(site) }
        if let length = VideoRef.durationLabel(item.durationS) { parts.append(length) }
        if let day = FeedDates.day(item, locale: locale, timeZone: timeZone) { parts.append(Copy.Lists.savedRow(day)) }
        return parts.joined(separator: " · ")
    }

    /// A wide row's trailing group: the row word and the age, "Transcript · 3h"; the age alone for a video with no word.
    static func trailing(state: VideoStateItem?, age: String?) -> String {
        [rowWord(state), age].compactMap { $0 }.joined(separator: " · ")
    }

    /// The triage column's second line: "channel · state word".
    static func triageLine(_ item: MediaFeedItem, state: VideoStateItem?) -> String {
        [clean(item.channel), rowWord(state)].compactMap { $0 }.joined(separator: " · ")
    }

    /// The picker's second line: "channel · length" (the provider's own mark, or its name when it has none, sits between).
    static func pickerLine(_ item: MediaFeedItem) -> String {
        [clean(item.channel), providerName(item), VideoRef.durationLabel(item.durationS) ?? Copy.Videos.lengthUnknown]
            .compactMap { $0 }.joined(separator: " · ")
    }

    /// The picker's third line: what Cicada holds and when it was saved ("Metadata only · saved Sep 29").
    static func pickerStateLine(_ item: MediaFeedItem, state: VideoStateItem?, locale: Locale = .autoupdatingCurrent,
                                timeZone: TimeZone = .autoupdatingCurrent) -> String {
        let day = FeedDates.day(item, locale: locale, timeZone: timeZone)
        let word: String? = {
            if let state, state.isQueued { return rowWord(state) }
            guard let state else { return Copy.Videos.stateNone }
            return stateTag(state.state)
        }()
        return [word, day.map(Copy.Lists.savedRow)].compactMap { $0 }.joined(separator: " · ")
    }

    /// A provider that has a bundled mark shows it; one that has not (Vimeo, Loom) is named in text — the Track L marks
    /// are a separate row (P12).
    static func providerName(_ item: MediaFeedItem) -> String? {
        switch VideoRef.resolve(item.url)?.provider {
        case .vimeo?: "Vimeo"
        case .loom?: "Loom"
        case .tiktok?: "TikTok"
        case .youtube?, .direct?, .local?, .twitch?, nil: nil
        }
    }

    static func showsYouTubeMark(_ item: MediaFeedItem) -> Bool {
        VideoRef.resolve(item.url)?.provider == .youtube || item.mediaType == "youtube"
    }

    /// The detail card's header line: "Video · youtube.com · 8:14" (the length when known).
    static func headerLine(_ item: MediaFeedItem) -> String {
        Eyebrow.text(FeedKind.video.singular, item.site ?? "", VideoRef.durationLabel(item.durationS) ?? "")
    }

    private static func clean(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return text
    }

    // MARK: The block's honesty lines

    /// What the record is and is not, in order: the fidelity/Sleep line first, then the frames caveat or the legacy help.
    /// Never "in your graph", never a claim about what Cicada itself saw.
    static func honestyLines(_ state: VideoStateItem) -> [String] {
        guard state.state != .none, state.state != .unknown else { return [] }
        var lines: [String] = []
        var first: [String] = []
        switch state.readBySleep {
        case true?: first.append(Copy.Videos.readBySleep)
        case false?: first.append(Copy.Videos.notReadBySleep)
        case nil: break
        }
        if state.fidelity == .approximate {
            first.append(state.engine == .videoLink ? Copy.Videos.approximateWording : Copy.Videos.approximateUnsaid)
        }
        if !first.isEmpty { lines.append(first.joined(separator: " ")) }
        if state.state == .recorded { lines.append(Copy.Videos.basisNotGiven) }
        else if hasFrames(state.state) { lines.append(Copy.Videos.sawNoFrames) }
        return lines
    }

    /// The first honesty line alone: whether Sleep has read the record, and whether its wording is approximate.
    static func sleepLine(_ state: VideoStateItem) -> String? { honestyLines(state).first { !isCaveat($0) } }

    /// The second: the frames caveat, or the legacy record's help.
    static func caveatLine(_ state: VideoStateItem) -> String? { honestyLines(state).first(where: isCaveat) }

    private static func isCaveat(_ line: String) -> Bool {
        line == Copy.Videos.sawNoFrames || line == Copy.Videos.basisNotGiven
    }

    /// <app> · <model> · Sep 28 — built from DATA only: the harness the record carries (its app name through
    /// `OriginIconography`), the model the turn join found, the day it was recorded. An app with no capture says its
    /// model was not shared (`ModelNames.agentLine`'s existing words); nothing is guessed.
    static func attribution(recordedBy: String?, recordedAt: String?, model: String?, effort: String?,
                            locale: Locale = .autoupdatingCurrent, timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        let agent = EvidenceSpeaker.agentName(harness: recordedBy, origin: nil)
        let line = ModelNames.agentLine(agent: agent, harness: recordedBy, model: model, effort: effort)
        let day = recordedDay(recordedAt, locale: locale, timeZone: timeZone)
        let parts = [line, day].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// "Sep 28" from the record's ISO instant.
    static func recordedDay(_ iso: String?, locale: Locale = .autoupdatingCurrent,
                            timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let iso, let date = VideoStateCache.parse(iso) else { return nil }
        var style = Date.FormatStyle().day().month(.abbreviated)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// "2:40 PM" from the record's ISO instant — the run card's done rows.
    static func recordedTime(_ iso: String?, locale: Locale = .autoupdatingCurrent,
                             timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let iso, let date = VideoStateCache.parse(iso) else { return nil }
        var style = Date.FormatStyle(date: .omitted, time: .shortened)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// The app's name for an agent a queue row or a record names, or a neutral "an agent" — DATA, never a literal.
    static func agentName(_ harness: String?) -> String {
        EvidenceSpeaker.agentName(harness: harness, origin: nil) ?? Copy.Videos.anAgent
    }

    static func hasFrames(_ state: VideoWatchState) -> Bool { state == .watched || state == .watchedAndTranscript }

    /// The reason a hand-back is shown with: the agent's own words when it gave them, else the code in plain words.
    static func failedReason(_ state: VideoStateItem) -> String {
        if let reason = state.failedReason?.trimmingCharacters(in: .whitespacesAndNewlines), !reason.isEmpty {
            return reason
        }
        switch state.failedCode {
        case .needsLogin?: return Copy.Videos.reasonNeedsLogin
        case .noCaptions?: return Copy.Videos.reasonNoCaptions
        case .notFound?: return Copy.Videos.reasonNotFound
        case .blocked?: return Copy.Videos.reasonBlocked
        case .failed?, nil: return Copy.Videos.reasonFailed
        }
    }
}

// MARK: - The button table

enum VideoAvailability: Equatable {
    case hidden
    case enabled(help: String?)
    case disabled(help: String)

    var isShown: Bool { self != .hidden }
}

/// The permission the person gave their agent to use their own signed-in browser (the one reading permission). `nil`
/// = this build cannot tell yet: the needs-login line says what it says when the permission is off, and offers no
/// button — the seam the reading branch fills (its settings model reads the switch; nothing here reads a host).
enum VideoBrowserPermission: Equatable { case off, on }

/// What a video's block draws under its Tag: at most one queue status, and the buttons the state allows.
struct VideoActionSet: Equatable {
    enum Status: Equatable {
        case none
        case queued(VideoWant)
        case pickedUp(by: String?, VideoWant)
        case failed(code: VideoFailCode?, reason: String)
    }

    var status: Status = .none
    var queueTranscript: VideoAvailability = .hidden
    var queueWatch: VideoAvailability = .hidden
    var showsRemove = false
    var showsTryAgain = false
    var showsOpenInBrowser = false
    /// `off` shows the sentence; `on` shows "may use your browser. Try again."; `nil` (this build cannot read the
    /// permission yet) shows none — no sentence points at a setting that is not there. Only a needs-login video has one.
    var browserLine: VideoBrowserPermission?
    var showsBrowserLine = false
    /// The link to Settings → Agents; only while the permission is known to be off.
    var showsAllowBrowser = false
}

enum VideoActions {
    /// One table for every state x queue combination (spec §4.7). `permission` is the reading branch's switch, `nil`
    /// until this build can read it.
    static func `for`(_ item: VideoStateItem?, permission: VideoBrowserPermission? = nil) -> VideoActionSet {
        guard let item else { return VideoActionSet() }
        var set = VideoActionSet()
        let want = item.want ?? .transcript
        switch item.queueState {
        case .queued?:
            set.status = .queued(want)
            set.showsRemove = true
            if want == .watch {
                set.queueTranscript = .disabled(help: Copy.Videos.watchIncludesTranscript)
            } else {
                set.queueWatch = .enabled(help: nil)
            }
        case .claimed?:
            set.status = .pickedUp(by: item.claimedBy, want)
            set.showsRemove = true
        case .failed?:
            set.status = .failed(code: item.failedCode, reason: VideoWords.failedReason(item))
            set.showsTryAgain = true
            set.showsRemove = true
            if item.failedCode == .needsLogin {
                set.showsOpenInBrowser = true
                set.showsBrowserLine = permission != nil
                set.browserLine = permission
                set.showsAllowBrowser = permission == .off
            }
        case nil:
            switch item.state {
            case .none, .unknown, .recorded:
                set.queueTranscript = .enabled(help: nil)
                set.queueWatch = .enabled(help: nil)
            case .transcript:
                set.queueWatch = .enabled(help: nil)
            case .watched:
                set.queueTranscript = .enabled(help: Copy.Videos.queueTranscriptForWording)
            case .watchedAndTranscript:
                break
            }
        }
        return set
    }
}

// MARK: - The queue's wording

enum VideoQueueLine {
    /// "4 queued · 1 picked up by an agent · 1 couldn't be done", a clause omitted at zero; nil when nothing is in
    /// the queue. One wording on the Feed strip and on Sleep's Details.
    static func text(_ summary: VideoSummary?) -> String? {
        guard let summary, summary.inQueue > 0 else { return nil }
        return Copy.Videos.queueLine(queued: summary.queued, claimed: summary.claimed, failed: summary.failed)
    }
}

// MARK: - Size (words and known minutes only)

/// Light, Medium or Heavy per the spec's thresholds (assumptions to tune from real runs): a transcript job is Light up
/// to 3 hours; a watch of 30 known minutes or less is Medium; a watch over 30 minutes or of unknown length, or a
/// transcript over 3 hours, is Heavy. Never a price (ruling 12), never a token, never an estimate of how long a run
/// will take (G107).
enum VideoSize: Equatable {
    case light, medium, heavy

    static let transcriptLimitSeconds = 3 * 3600
    static let watchMediumLimitSeconds = 30 * 60

    static func of(want: VideoWant, seconds: Int?) -> VideoSize {
        switch want {
        case .transcript:
            if let seconds, seconds > transcriptLimitSeconds { return .heavy }
            return .light
        case .watch:
            guard let seconds, seconds > 0 else { return .heavy }
            return seconds <= watchMediumLimitSeconds ? .medium : .heavy
        }
    }

    /// True for a Heavy verdict that rests on no known length.
    static func isLengthUnknown(want: VideoWant, seconds: Int?) -> Bool {
        want == .watch && (seconds ?? 0) <= 0
    }

    var word: String {
        switch self {
        case .light: Copy.Videos.sizeLight
        case .medium: Copy.Videos.sizeMedium
        case .heavy: Copy.Videos.sizeHeavy
        }
    }
}

struct VideoSizeSummary: Equatable {
    var light = 0
    var medium = 0
    var heavy = 0
    var heavyUnknown = 0
    /// Known seconds across the WATCH items only.
    var watchSeconds = 0
    var watchUnknown = 0

    static func of(_ picks: [(want: VideoWant, seconds: Int?)]) -> VideoSizeSummary {
        var out = VideoSizeSummary()
        for pick in picks {
            switch VideoSize.of(want: pick.want, seconds: pick.seconds) {
            case .light: out.light += 1
            case .medium: out.medium += 1
            case .heavy:
                out.heavy += 1
                if VideoSize.isLengthUnknown(want: pick.want, seconds: pick.seconds) { out.heavyUnknown += 1 }
            }
            if pick.want == .watch {
                if let seconds = pick.seconds, seconds > 0 { out.watchSeconds += seconds } else { out.watchUnknown += 1 }
            }
        }
        return out
    }

    var line: String {
        Copy.Videos.sizeLine(light: light, medium: medium, heavy: heavy, heavyUnknown: heavyUnknown)
    }

    /// Known minutes, rounded up ("9:48" is "10 min").
    var watchMinutes: Int { (watchSeconds + 59) / 60 }

    var minutesLine: String? { Copy.Videos.minutesLine(minutes: watchMinutes, unknown: watchUnknown) }
}

// MARK: - The record's first quote

enum VideoQuote {
    /// The first `media` turn of a watch record — what the video said at a time — as the block shows it: the words
    /// without markup, in curly quotes, and its place in the video. Nil when the record holds no quote.
    static func first(_ doc: EpisodeText) -> (text: String, time: String?)? {
        let scalars = ScalarText(doc.text)
        for turn in doc.turns where turn.role == "media" {
            let raw = scalars.slice(turn.contentStart, turn.end)
            var words = ExcerptText.quoteParts(before: "", span: raw, after: "").span
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !words.isEmpty else { continue }
            if !(words.hasPrefix("\u{201C}") || words.hasPrefix("\"")) { words = "\u{201C}" + words + "\u{201D}" }
            return (words, EvidenceSpeaker.mediaTime(turn.t))
        }
        return nil
    }
}
