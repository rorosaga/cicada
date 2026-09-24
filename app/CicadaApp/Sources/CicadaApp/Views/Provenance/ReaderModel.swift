import Foundation

// The Reader's decisions, pure and tested (design §4.4, §4.10
// `ReaderTurnsTests`), so `ReaderColumn` is a renderer: who is speaking,
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

/// R-DI11 — a turn's washes as `CitedSpan` segments: the cited span `.current` (the wash and the
/// accent underline, DR-18), another span the same entity cites `.other` (`washSoft`), a derived
/// match `.mention` (semibold, never washed, DR-57). Scalar offsets, as `ReaderLayout` computes them;
/// a wash that does not fit, or starts inside an earlier one, is skipped — never trapped on. At one
/// offset the cited span wins over a soft one.
enum ReaderText {
    static func segments(_ block: ReaderBlock) -> [CitedSpan.Segment] {
        let text = ScalarText(block.text)
        func rank(_ s: ReaderWash.Style) -> Int { s == .other ? 1 : 0 }
        let washes = block.washes
            .filter { $0.range.lowerBound >= 0 && $0.range.upperBound <= text.count && !$0.range.isEmpty }
            .sorted { ($0.range.lowerBound, rank($0.style)) < ($1.range.lowerBound, rank($1.style)) }
        var out: [CitedSpan.Segment] = []
        var cursor = 0
        for wash in washes where wash.range.lowerBound >= cursor {
            if wash.range.lowerBound > cursor {
                out.append(.init(text: text.slice(cursor, wash.range.lowerBound), mark: .plain))
            }
            let mark: CitedSpan.Mark = switch wash.style {
            case .focus: .current
            case .other: .other
            case .mention: .mention
            }
            out.append(.init(text: text.slice(wash.range.lowerBound, wash.range.upperBound), mark: mark))
            cursor = wash.range.upperBound
        }
        if cursor < text.count { out.append(.init(text: text.slice(cursor, text.count), mark: .plain)) }
        return out
    }
}

/// One highlighted stretch inside a turn, as scalar offsets LOCAL to the
/// turn's text.
struct ReaderWash: Hashable {
    enum Style: Hashable {
        /// The cited span: the accent wash plus its underline (DR-18, R-DI11).
        case focus
        /// A derived match: bold, never washed (§4.9).
        case mention
        /// Another span the same entity cites: the soft wash, no underline (P4).
        case other
    }
    let range: Range<Int>
    let style: Style
}

struct ReaderBlock: Hashable, Identifiable {
    /// A block is one CHUNK of one turn (final review): the turn's server
    /// index plus the chunk's place in it, so scrolling, landing and both
    /// rotors address the piece of text that is actually on screen.
    struct Key: Hashable {
        let turn: Int
        let chunk: Int
    }

    let index: Int
    /// 0 for a turn's first chunk — the only one that carries the speaker line.
    let chunk: Int
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

    var id: Key { Key(turn: index, chunk: chunk) }
    /// Only a turn's first chunk draws the speaker line and joins the Turns
    /// rotor; the rest read on as the same turn.
    var startsTurn: Bool { chunk == 0 }
    /// The block the landing and the cited-passages rotor belong to.
    var holdsFocus: Bool { washes.contains { $0.style == .focus || $0.style == .mention } }
}

enum ReaderLayout {
    /// The most scalars one block's `Text` holds (final review). SwiftUI lays
    /// a `Text` out whole: a single 400,000-character turn — a note, a log
    /// pasted into a chat export, a file with no headings, all within the
    /// Reader's own cap (R-PB5) — took 11.7 s on the main thread for the
    /// first layout and 5.7 s more when the wash faded in, measured offscreen
    /// in the Reader's configuration (`textSelection` was not the cause:
    /// 11.1 s without it). The same text as ~4K pieces laid out in 0.11 s.
    static let chunkLimit = 4_000

    /// The document as blocks: each server turn (`turns[]` — the client runs
    /// no marker regex of its own, R-PB3) cut into chunks of at most
    /// `chunkLimit` scalars (`chunks`). Every range is intersected with each
    /// chunk of each turn's CONTENT (the marker line prefix is replaced by the
    /// speaker label), so a span that crosses a turn or chunk boundary is
    /// split into one wash per block (§4.4). Offsets past a truncated text
    /// are dropped.
    static func blocks(doc: EpisodeText, scalars: ScalarText, focus: Range<Int>?,
                       focusStyle: ReaderWash.Style, others: [Range<Int>] = [],
                       locale: Locale = .autoupdatingCurrent,
                       timeZone: TimeZone = .autoupdatingCurrent) -> [ReaderBlock] {
        doc.turns.flatMap { turn -> [ReaderBlock] in
            let content = scalars.clamped(turn.contentStart, turn.end)
            guard content.upperBound > content.lowerBound || turn.role == "page" else { return [] }
            let speaker = EvidenceSpeaker.turnSpeaker(turn, harness: doc.harness, origin: doc.origin)
            let mark = turn.role == "assistant"
                ? EvidenceSpeaker.agentOrigin(harness: doc.harness, origin: doc.origin) : nil
            let time = ReaderTime.label(turn.ts, locale: locale, timeZone: timeZone)
            return chunks(content, in: scalars).enumerated().map { n, piece in
                var washes: [ReaderWash] = []
                func add(_ range: Range<Int>, _ style: ReaderWash.Style) {
                    let lo = max(range.lowerBound, piece.lowerBound)
                    let hi = min(range.upperBound, piece.upperBound)
                    guard hi > lo else { return }
                    washes.append(ReaderWash(range: (lo - piece.lowerBound)..<(hi - piece.lowerBound), style: style))
                }
                if let focus { add(focus, focusStyle) }
                for other in others where other != focus { add(other, .other) }
                washes.sort { $0.range.lowerBound < $1.range.lowerBound }
                return ReaderBlock(
                    index: turn.index, chunk: n, role: turn.role, speaker: speaker, mark: mark, time: time,
                    text: scalars.slice(piece.lowerBound, piece.upperBound),
                    contentStart: piece.lowerBound, washes: washes)
            }
        }
    }

    /// `content` cut into ranges of at most `limit` scalars. A cut prefers a
    /// line break in the back half of the window, then a space there, and
    /// the break itself belongs to neither side (a `Text` ending in "\n"
    /// would draw a blank line; the blocks already stack one per line). With
    /// neither, it cuts hard — stepping back off a combining mark or a
    /// joiner so a grapheme is not torn between two `Text`s. An empty
    /// content (a page with no body) is one empty range.
    static func chunks(_ content: Range<Int>, in scalars: ScalarText, limit: Int = chunkLimit) -> [Range<Int>] {
        guard content.count > limit else { return [content] }
        var out: [Range<Int>] = []
        var start = content.lowerBound
        while content.upperBound - start > limit {
            let window = (start + limit / 2)..<(start + limit)
            let s = scalars.scalars
            if let nl = window.reversed().first(where: { s[$0] == "\n" })
                ?? window.reversed().first(where: { s[$0] == " " }) {
                // A CRLF's "\r" goes with its "\n", never onto the chunk's end.
                out.append(start..<(nl > start && s[nl - 1] == "\r" ? nl - 1 : nl))
                start = nl + 1
            } else {
                var cut = start + limit
                while cut > window.lowerBound,
                      s[cut].properties.isGraphemeExtend || s[cut] == "\u{200D}" || s[cut - 1] == "\u{200D}" {
                    cut -= 1
                }
                out.append(start..<cut)
                start = cut
            }
        }
        out.append(start..<content.upperBound)
        return out
    }

    /// The block holding `offset`, for landing. A stale focus still lands
    /// near where the words were (scrolling is not highlighting).
    static func blockID(containing offset: Int, in blocks: [ReaderBlock]) -> ReaderBlock.Key? {
        (blocks.last { $0.contentStart <= offset } ?? blocks.first)?.id
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

// MARK: - The navigator and "Noted from this conversation" (§4.4, P4)

enum ReaderNavigator {
    /// The spans the navigator steps through, in document order: the ranges
    /// the SUBJECT's claims cite here when the Reader was opened for an
    /// entity, else every cited range (a Reader opened from the inbox or a
    /// history row steps through all of them, §4.4). Stale rows carry no
    /// offsets (R-PB2), so they are never a stop; duplicates fold.
    static func stops(_ citations: [EpisodeCitation], subjectId: String?) -> [Range<Int>] {
        let ranged = citations.filter { $0.range != nil }
        let mine = subjectId.map { id in ranged.filter { $0.subjectId == id } } ?? []
        let chosen = mine.isEmpty ? ranged : mine
        var seen = Set<Range<Int>>()
        return chosen.compactMap(\.range)
            .filter { seen.insert($0).inserted }
            .sorted { $0.lowerBound != $1.lowerBound ? $0.lowerBound < $1.lowerBound : $0.upperBound < $1.upperBound }
    }

    /// Where `focus` sits among the stops — exact match first, else the first
    /// stop that overlaps it — or nil when it is not one of them.
    static func position(of focus: Range<Int>?, in stops: [Range<Int>]) -> Int? {
        guard let focus else { return nil }
        return stops.firstIndex(of: focus) ?? stops.firstIndex { $0.overlaps(focus) }
    }

    /// The stop `delta` steps from `current` (clamped, never wrapping — the
    /// first and last passage are ends, not a loop). With no current stop,
    /// forward goes to the first and back to the last.
    static func step(from current: Int?, count: Int, by delta: Int) -> Int? {
        guard count > 0 else { return nil }
        guard let current else { return delta >= 0 ? 0 : count - 1 }
        return min(max(current + delta, 0), count - 1)
    }

    /// "2 of 5 cited here".
    static func label(position: Int?, count: Int) -> String {
        guard count > 0 else { return "" }
        let n = UsageFormat.count(count)
        guard let position else { return "\(n) cited here" }
        return "\(UsageFormat.count(position + 1)) of \(n) cited here"
    }
}

extension ReaderPresentation {
    /// A jump inside the Reader (a navigator step or a "Noted from this
    /// conversation" row) replaces the target's focus with a citation's own,
    /// judged by that citation's own flags: a derived row bolds, a grown row
    /// says so, and the target's banners no longer apply to these words.
    static func citation(_ c: EpisodeCitation, truncated: Bool, textCount: Int) -> ReaderPresentation {
        guard let range = c.range, range.lowerBound < textCount else {
            return ReaderPresentation(focus: nil, focusStyle: .focus, banners: truncated ? [.truncated] : [],
                                      landing: nil)
        }
        var banners: [ReaderBanner] = []
        if c.derived { banners.append(.derived) }
        if c.grown { banners.append(.grown) }
        if truncated { banners.append(.truncated) }
        return ReaderPresentation(focus: range, focusStyle: c.derived ? .mention : .focus, banners: banners,
                                  landing: range.lowerBound)
    }
}
