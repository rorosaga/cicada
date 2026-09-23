import Foundation

// The Reader's decisions, pure and tested (design §4.4, §4.10
// `ReaderTurnsTests`), so `ReaderInspector` is a renderer: who is speaking,
// what to wash, what to say about it, and where to land.

// MARK: - Who is speaking

enum EvidenceSpeaker {
    /// The words the one marker parser matches (`evidence._TURN_RE`). The
    /// chat importer's `turns` sidecar stores the ROLE as `speaker`
    /// (`conversations._turn_stamps`), so a sidecar `speaker` that is one of
    /// these is a role, not a name, and must never print as "user said".
    static let markerWords: Set<String> = ["user", "human", "assistant", "ai", "system", "unknown"]

    /// A product name for the agent in a conversation, or nil when nothing
    /// says which agent it was. The harness wins (a Stop-hook or MCP episode
    /// stamps it); an imported export names its vendor; `mcp`/`unknown` name
    /// no product, so they fall through to "The agent". Never the MODEL:
    /// conversation `model` is reserved-null (§4.9) and "who spoke" is not
    /// "who wrote the belief".
    static func agentName(harness: String?, origin: String?) -> String? {
        if let h = harness?.trimmingCharacters(in: .whitespaces), !h.isEmpty, h != "unknown", h != "mcp" {
            return OriginIconography.label(for: h)
        }
        switch origin {
        case "claude-export": return "Claude"
        case "chatgpt-export": return "ChatGPT"
        case "gemini-export": return "Gemini"
        default: return nil
        }
    }

    /// The origin id whose mark belongs beside `agentName`'s words — the same
    /// precedence, so a label and its mark never disagree, and a named service
    /// always wears its real mark (the round-3 brief: "use logos whenever
    /// possible"). An import's mark is its vendor's (`chatgpt-export` →
    /// the ChatGPT mark, `OriginIconography.logoName`); nil when no agent is
    /// named.
    static func agentOrigin(harness: String?, origin: String?) -> String? {
        if let h = harness?.trimmingCharacters(in: .whitespaces), !h.isEmpty, h != "unknown", h != "mcp" {
            return h
        }
        switch origin {
        case "claude-export", "chatgpt-export", "gemini-export": return origin
        default: return nil
        }
    }

    /// A real name from a meeting sidecar, or nil. Role words are not names.
    static func named(_ speaker: String?) -> String? {
        guard let s = speaker?.trimmingCharacters(in: .whitespaces), !s.isEmpty,
              !markerWords.contains(s.lowercased()) else { return nil }
        return s
    }

    /// The speaker line over one turn. R4 counts `system` and `unknown`
    /// markers as the person's side (so a chip there reads "You said"); the
    /// Reader is allowed to be more precise about what the line actually was.
    /// A meeting speaker is never "You" (R-N2): with no confirmed name it is
    /// "Someone else".
    static func turnSpeaker(_ turn: EpisodeTurn, harness: String?, origin: String?) -> String {
        switch turn.role {
        case "assistant":
            return agentName(harness: harness, origin: origin) ?? Copy.Provenance.theAgent
        case "page":
            return ""
        case "speaker":
            return named(turn.speaker) ?? Copy.Provenance.someoneElse
        default:
            switch turn.marker {
            case "system": return Copy.Provenance.setupMessage
            case "unknown": return Copy.Provenance.unlabelledMessage
            default: return Copy.you
            }
        }
    }
}

// MARK: - Times (only ever the stored one)

enum ReaderTime {
    /// A turn's time as the Reader prints it, or nil. Only a time the episode
    /// STORES is shown (§4.4 — "No time is ever inferred"): an aware ISO stamp
    /// becomes a short local clock time; a naive one (G114: a bank holds naive
    /// and aware stamps side by side) is read in the viewer's zone, as it was
    /// written; a meeting offset ("00:23:41") is already what a person would
    /// say and passes through.
    static func label(_ ts: String?, locale: Locale = .autoupdatingCurrent,
                      timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let raw = ts?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        if raw.range(of: #"^\d{1,2}:\d{2}(:\d{2})?$"#, options: .regularExpression) != nil { return raw }
        guard let date = instant(raw, timeZone: timeZone) else { return nil }
        var style = Date.FormatStyle(date: .omitted, time: .shortened)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// An ISO stamp in any of the shapes a bank holds, or nil.
    static func instant(_ raw: String, timeZone: TimeZone = .autoupdatingCurrent) -> Date? {
        let aware = ISO8601DateFormatter()
        aware.formatOptions = [.withInternetDateTime]
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = aware.date(from: raw) ?? fractional.date(from: raw) { return d }
        let naive = DateFormatter()
        naive.locale = Locale(identifier: "en_US_POSIX")
        naive.timeZone = timeZone
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            naive.dateFormat = format
            if let d = naive.date(from: raw) { return d }
        }
        return nil
    }

    /// "3 Sep 2026" for the header's meta line, from the episode's timestamp
    /// or, failing that, the date in its id (`ep_YYYY-MM-DD_nnn`, G114).
    static func day(timestamp: String?, episode: String, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent, withYear: Bool = true) -> String? {
        let date = timestamp.flatMap { instant($0, timeZone: timeZone) } ?? episodeDate(episode, timeZone: timeZone)
        guard let date else { return nil }
        var style = withYear ? Date.FormatStyle().day().month(.abbreviated).year()
                             : Date.FormatStyle().day().month(.abbreviated)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    /// The day an episode id was minted on, or nil for a page id.
    static func episodeDate(_ episode: String, timeZone: TimeZone = .autoupdatingCurrent) -> Date? {
        guard episode.hasPrefix("ep_"), episode.count >= 13 else { return nil }
        let day = String(episode.dropFirst(3).prefix(10))
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = timeZone
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: day)
    }
}

// MARK: - What to wash

/// One highlighted stretch inside a turn, as scalar offsets LOCAL to the
/// turn's text.
struct ReaderWash: Hashable {
    enum Style: Hashable {
        /// The cited span: the dandelion wash plus the margin bar (§4.4).
        case focus
        /// A derived match: bold, never washed (§4.9).
        case mention
        /// Another span the same entity cites: a fainter wash, no bar (P4).
        case other
    }
    let range: Range<Int>
    let style: Style
}

struct ReaderBlock: Hashable, Identifiable {
    let index: Int
    let role: String
    let speaker: String
    /// The origin whose mark sits beside an agent's speaker line (§4.4: "a
    /// harness mark with its label"); nil for the person, a page, or an
    /// agent nothing names.
    let mark: String?
    let time: String?
    let text: String
    /// Absolute offset of `text`'s first scalar in the document.
    let contentStart: Int
    let washes: [ReaderWash]

    var id: Int { index }
    /// The block the margin bar and the landing belong to.
    var holdsFocus: Bool { washes.contains { $0.style == .focus || $0.style == .mention } }
}

enum ReaderLayout {
    /// The document as blocks, one per server turn (`turns[]` — the client
    /// runs no marker regex of its own, R-PB3). Every range is intersected
    /// with each turn's CONTENT (the marker line prefix is replaced by the
    /// speaker label), so a span that crosses a turn boundary is split into
    /// one wash per turn (§4.4). Offsets past a truncated text are dropped.
    static func blocks(doc: EpisodeText, scalars: ScalarText, focus: Range<Int>?,
                       focusStyle: ReaderWash.Style, others: [Range<Int>] = [],
                       locale: Locale = .autoupdatingCurrent,
                       timeZone: TimeZone = .autoupdatingCurrent) -> [ReaderBlock] {
        doc.turns.compactMap { turn in
            let content = scalars.clamped(turn.contentStart, turn.end)
            guard content.upperBound > content.lowerBound || turn.role == "page" else { return nil }
            var washes: [ReaderWash] = []
            func add(_ range: Range<Int>, _ style: ReaderWash.Style) {
                let lo = max(range.lowerBound, content.lowerBound)
                let hi = min(range.upperBound, content.upperBound)
                guard hi > lo else { return }
                washes.append(ReaderWash(range: (lo - content.lowerBound)..<(hi - content.lowerBound), style: style))
            }
            if let focus { add(focus, focusStyle) }
            for other in others where other != focus { add(other, .other) }
            washes.sort { $0.range.lowerBound < $1.range.lowerBound }
            return ReaderBlock(
                index: turn.index, role: turn.role,
                speaker: EvidenceSpeaker.turnSpeaker(turn, harness: doc.harness, origin: doc.origin),
                mark: turn.role == "assistant"
                    ? EvidenceSpeaker.agentOrigin(harness: doc.harness, origin: doc.origin) : nil,
                time: ReaderTime.label(turn.ts, locale: locale, timeZone: timeZone),
                text: scalars.slice(content.lowerBound, content.upperBound),
                contentStart: content.lowerBound, washes: washes)
        }
    }

    /// The block holding `offset`, for landing. A stale focus still lands
    /// near where the words were (scrolling is not highlighting).
    static func blockIndex(containing offset: Int, in blocks: [ReaderBlock]) -> Int? {
        blocks.last { $0.contentStart <= offset }?.index ?? blocks.first?.index
    }
}

// MARK: - What to say about it, and where to land

enum ReaderBanner: Hashable {
    case stale, grown, inferred, derived, notFound, truncated
}

struct ReaderPresentation: Hashable {
    let focus: Range<Int>?
    let focusStyle: ReaderWash.Style
    let banners: [ReaderBanner]
    /// Absolute offset to scroll to; nil opens at the top.
    let landing: Int?

    /// The honesty rules of §4.9 in one function: stale never washes (and is
    /// said out loud), grown washes and says so, derived bolds and says so,
    /// inferred shows no quote. The target's own `derived` flag wins over the
    /// server's asserted focus — an inbox cause found by name is still found
    /// by name when the Reader re-asks by offsets (R-PB16).
    static func resolve(target: ReaderTarget, doc: EpisodeText, textCount: Int) -> ReaderPresentation {
        var banners: [ReaderBanner] = []
        var focus: Range<Int>?
        var style: ReaderWash.Style = .focus
        var landing: Int?
        switch target.focus {
        case let .span(start, end, _, derived):
            if doc.focus?.stale == true {
                banners.append(.stale)
                landing = start
            } else {
                focus = doc.focus?.range ?? (end > start ? start..<end : nil)
                style = derived || doc.focus?.derived == true ? .mention : .focus
                if style == .mention { banners.append(.derived) }
                if doc.focus?.grown == true { banners.append(.grown) }
            }
        case .mention:
            if let range = doc.focus?.range {
                focus = range
                style = .mention
                banners.append(.derived)
            } else {
                banners.append(.notFound)
            }
        case .inferred:
            banners.append(.inferred)
        case .stale:
            banners.append(.stale)
        case .none:
            break
        }
        if let range = focus, range.lowerBound >= textCount {
            // The words sit past the 400,000-character cap (R-PB5): nothing
            // on screen to wash or land on. The truncated banner says why.
            focus = nil
        }
        if doc.truncated { banners.append(.truncated) }
        return ReaderPresentation(focus: focus, focusStyle: style, banners: banners,
                                  landing: focus?.lowerBound ?? landing.map { min($0, max(0, textCount - 1)) })
    }
}

enum ReaderHeader {
    /// The Stop hook's own stamp (`transcript_capture.CAPTURE_KIND`). It is
    /// not the only one: Telegram's `/remind` note is `capture_kind:
    /// reminder`, and that episode holds exactly what was sent — so the line
    /// below keys on this value, never on "some capture kind is present".
    static let hookCaptureKind = "transcript"

    /// The capture-honesty line (§4.4, G105): a Stop-hook episode keeps the
    /// person's turns and each final reply only; an import says whose export
    /// it was; anything else says nothing rather than guess.
    static func captureLine(_ doc: EpisodeText) -> String? {
        if doc.isPage { return nil }
        if doc.captureKind == hookCaptureKind { return Copy.Provenance.captureHonesty }
        if let origin = doc.origin, origin.hasSuffix("-export"),
           let vendor = EvidenceSpeaker.agentName(harness: nil, origin: origin) {
            return Copy.Provenance.importedFrom(vendor)
        }
        return nil
    }

    /// "Claude Code · 3 Sep 2026 · 42 turns". A page has no turns to count.
    static func meta(_ doc: EpisodeText, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if doc.isPage {
            parts.append(Copy.Provenance.fromThePage)
        } else if let agent = EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin) {
            parts.append(agent)
        }
        if let day = ReaderTime.day(timestamp: doc.timestamp, episode: doc.episode, locale: locale,
                                    timeZone: timeZone) {
            parts.append(day)
        }
        if !doc.isPage, !doc.turns.isEmpty { parts.append(Copy.Provenance.turnCount(doc.turns.count)) }
        return parts.joined(separator: " · ")
    }

    /// The mark to draw: the harness, else the origin, else nothing known.
    static func markOrigin(harness: String?, origin: String?) -> String {
        if let h = harness, !h.isEmpty { return h }
        if let o = origin, !o.isEmpty { return o }
        return "unknown"
    }
}
