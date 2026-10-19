import Foundation

/// The Reader's chat layout (owner, 2026-10-19: "looking at it as a chat layout … like a historical chat where you
/// have to go up to go back in history"), pure and tested (`ReaderChatTests`), so `ReaderChatRows` only draws it.
///
/// A conversation — a Messages sitting, a Claude Code / Codex / Cursor / Gemini session, a chat export, a relayed
/// connector chat — reads as a chat: the person's turns on the right in a bubble, the other party's on the left as
/// plain text, a day separator where the day changes, the other party's face or mark and a time once per run, no
/// "turn N". Everything else the Reader opens (a page, a saved link, a note, a watched day, a feed item) keeps the
/// document view (`isChat`). The rows are built over `ReaderLayout.blocks`, so every wash, every landing and both
/// rotors address the very blocks the document view would.
enum ReaderChat {
    /// A turn longer than this (scalars) or with more lines than `collapseLines` starts folded to a preview.
    static let collapseScalars = 1_000
    static let collapseLines = 12
    /// The folded preview: at most this many scalars and lines, cut at a line break or a space.
    static let previewScalars = 480
    static let previewLines = 6
    /// Two turns of the same side further apart than this start a new run (and show their time again).
    static let runBreak: TimeInterval = 15 * 60

    /// The origin Messages sittings carry (`messages_source.ORIGIN`).
    static let messagesOrigin = "imessage"
    /// The prefix of a Messages sitting's `source_id` (`messages_source.SOURCE_PREFIX`), before the chat's id.
    static let messagesSourcePrefix = "imessage:"

    // MARK: Which documents are chats

    /// A conversation, as opposed to a document: an episode (never a page or a watch record, never a feed item or a
    /// calendar entry) with at least one turn a conversation marker opened — the other party's (`assistant`,
    /// `speaker`) or the person's own written `user:`. A note with no marker is one marker-less block and stays a
    /// document.
    static func isChat(_ doc: EpisodeText) -> Bool {
        guard !doc.isPage, !doc.isPageRead, doc.watch == nil, EvidenceSpeaker.sourceSpeaker(doc.origin) == nil else {
            return false
        }
        return doc.turns.contains { turn in
            switch turn.role {
            case "assistant", "speaker": return true
            case "user": return turn.marker != nil
            default: return false
            }
        }
    }

    /// The Messages chat a sitting belongs to (`imessage:<chat>:<first key>`), for its picture; nil for anything else.
    static func messagesChat(_ doc: EpisodeText) -> String? {
        guard doc.origin == messagesOrigin, let id = doc.conversationId, id.hasPrefix(messagesSourcePrefix) else {
            return nil
        }
        let chat = id.dropFirst(messagesSourcePrefix.count).prefix { $0 != ":" }
        return chat.isEmpty ? nil : String(chat)
    }

    // MARK: Rows

    enum Side: Hashable {
        /// The person: right-aligned, in a bubble.
        case person
        /// Anyone else — an agent, a contact, a meeting speaker, an attached file: left-aligned, plain.
        case other
    }

    /// What sits beside the other party's name at the head of a run.
    enum Avatar: Hashable {
        /// An app's or a service's mark (DR-52) — an agent's harness or an export's vendor.
        case mark(String)
        /// A person's face: the chat's picture in Messages, else a monogram.
        case face(String)
        case none
    }

    /// The line at the head of a run: the face or mark, the name when it changed, the run's first time.
    struct Header: Hashable {
        let avatar: Avatar
        let name: String?
        let time: String?
    }

    /// A bubble's place in its turn, for its corners: a long turn is several blocks (`ReaderLayout.chunks`), drawn
    /// as one bubble.
    enum Piece: Hashable { case whole, first, middle, last }

    /// The space above a row.
    enum Gap: Hashable { case none, inRun, newRun, section }

    struct Message: Hashable {
        /// The block to draw — a folded turn's preview is its first block cut short, washes clipped to it.
        let block: ReaderBlock
        let side: Side
        let header: Header?
        let piece: Piece
        /// The words the person reads out with this row, its time included (VoiceOver, the rotors).
        let speaker: String
        let time: String?
        let folded: Bool
    }

    struct Row: Identifiable, Hashable {
        enum ID: Hashable {
            case day(Int)
            case block(ReaderBlock.Key)
            case toggle(Int)
        }
        enum Kind: Hashable {
            /// "Today", "Yesterday", "Monday", "Sep 3" — computed when read (DR-58).
            case day(String)
            /// G110 gate B2 — Cicada's own line where a conversation's middle (or part of a reply) was not kept.
            case gap(ReaderBlock, words: String)
            case message(Message)
            /// "Show more" / "Show less" under a long turn.
            case toggle(turn: Int, side: Side, expanded: Bool)
        }
        let id: ID
        let kind: Kind
        let gap: Gap

        /// What `ScrollViewProxy.scrollTo` and the rotors address: a block row by its `ReaderBlock.Key`, exactly as
        /// the document view does, so landing and the navigator are unchanged.
        var scrollID: AnyHashable {
            if case let .block(key) = id { return AnyHashable(key) }
            return AnyHashable(id)
        }

        var block: ReaderBlock? {
            switch kind {
            case let .message(m): m.block
            case let .gap(b, _): b
            default: nil
            }
        }
    }

    /// The chat rows for `blocks` (all of the document's, in order). `expanded` holds the turns the person unfolded;
    /// `keepOpen` the turns that must never fold (the landing turn, a turn holding a cited span), so a wash is always
    /// on screen. `now` is when the Reader reads it (DR-58).
    static func rows(blocks: [ReaderBlock], doc: EpisodeText, expanded: Set<Int> = [], keepOpen: Set<Int> = [],
                     now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> [Row] {
        let turnsByIndex = Dictionary(doc.turns.map { ($0.index, $0) }, uniquingKeysWith: { a, _ in a })
        let docDate = doc.timestamp.flatMap { ReaderTime.instant($0, timeZone: timeZone) }
            ?? ReaderTime.episodeDate(doc.episode, timeZone: timeZone)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        calendar.locale = locale
        let chat = messagesChat(doc) != nil

        // A turn's blocks, grouped, so a folded turn draws one preview and a long one one bubble.
        var order: [Int] = []
        var pieces: [Int: [ReaderBlock]] = [:]
        for block in blocks {
            if pieces[block.index] == nil { order.append(block.index) }
            pieces[block.index, default: []].append(block)
        }

        var out: [Row] = []
        var day: DateComponents?
        var last: (side: Side, speaker: String, date: Date?)?
        var lastOtherName: String?
        var lastPersonName: String?
        for (position, index) in order.enumerated() {
            guard let turnBlocks = pieces[index], let head = turnBlocks.first else { continue }
            let turn = turnsByIndex[index]
            let date = turn?.ts.flatMap { ReaderTime.instant($0, timeZone: timeZone) }
                ?? (position == 0 ? docDate : nil)

            // Day separators: the day of the first turn, then wherever it changes.
            if let date {
                let key = calendar.dateComponents([.year, .month, .day], from: date)
                if key != day {
                    day = key
                    out.append(Row(id: .day(index), kind: .day(dayLabel(date, now: now, locale: locale, timeZone: timeZone)),
                                   gap: out.isEmpty ? .none : .section))
                    last = nil
                }
            }

            if head.role == "gap" {
                // Cicada's note sits between the turns it separates; a reply resumed after it reads on as the same run.
                for block in turnBlocks {
                    out.append(Row(id: .block(block.id), kind: .gap(block, words: gapWords(block.text, locale: locale, timeZone: timeZone)),
                                   gap: out.isEmpty ? .none : .newRun))
                }
                continue
            }

            let side = side(of: head)
            let speaker = head.speaker
            let startsRun: Bool = {
                guard let last else { return true }
                if last.side != side || last.speaker != speaker { return true }
                if let a = last.date, let b = date, b.timeIntervalSince(a) > runBreak { return true }
                return false
            }()
            var header: Header?
            if startsRun {
                switch side {
                case .other:
                    let name: String? = speaker.isEmpty || speaker == lastOtherName ? nil : speaker
                    if !speaker.isEmpty { lastOtherName = speaker }
                    let avatar = avatar(for: head, doc: doc, chat: chat)
                    if name != nil || avatar != .none || head.time != nil {
                        header = Header(avatar: avatar, name: name, time: head.time)
                    }
                case .person:
                    // "You" is said by the side; a setup or unlabelled message names itself once.
                    let name: String? = speaker == Copy.you || speaker == lastPersonName ? nil : speaker
                    lastPersonName = speaker
                    if name != nil || head.time != nil { header = Header(avatar: .none, name: name, time: head.time) }
                }
            }
            last = (side, speaker, date ?? last?.date)

            let open = keepOpen.contains(index) || expanded.contains(index)
            let foldable = isLong(turnBlocks)
            let gapAbove: Gap = out.isEmpty ? .none : (startsRun ? .newRun : .inRun)
            if foldable && !open, let preview = preview(head) {
                out.append(Row(id: .block(head.id), kind: .message(Message(
                    block: preview, side: side, header: header, piece: .whole, speaker: speaker, time: head.time,
                    folded: true)), gap: gapAbove))
            } else {
                for (n, block) in turnBlocks.enumerated() {
                    let piece: Piece = turnBlocks.count == 1 ? .whole
                        : n == 0 ? .first : n == turnBlocks.count - 1 ? .last : .middle
                    out.append(Row(id: .block(block.id), kind: .message(Message(
                        block: block, side: side, header: n == 0 ? header : nil, piece: piece, speaker: speaker,
                        time: head.time, folded: false)), gap: n == 0 ? gapAbove : .none))
                }
            }
            if foldable && !keepOpen.contains(index) {
                out.append(Row(id: .toggle(index), kind: .toggle(turn: index, side: side, expanded: open), gap: .none))
            }
        }
        return out
    }

    /// The person's side: their own turns, and the setup / unlabelled lines R4 counts as theirs.
    static func side(of block: ReaderBlock) -> Side {
        block.role == "user" ? .person : .other
    }

    static func avatar(for block: ReaderBlock, doc: EpisodeText, chat: Bool) -> Avatar {
        switch block.role {
        case "assistant":
            // A texted agent wears the chat's own picture, as the person sees it in Messages (G179).
            if chat { return .face(block.speaker) }
            return EvidenceSpeaker.agentOrigin(harness: doc.harness, origin: doc.origin).map(Avatar.mark) ?? .none
        case "speaker":
            return .face(block.speaker)
        default:
            return .none
        }
    }

    // MARK: Folding

    /// Whether a turn (all of its blocks) is long enough to start folded.
    static func isLong(_ blocks: [ReaderBlock]) -> Bool {
        if blocks.count > 1 { return true }
        guard let only = blocks.first else { return false }
        if only.text.unicodeScalars.count > collapseScalars { return true }
        var lines = 1
        for scalar in only.text.unicodeScalars where scalar == "\n" {
            lines += 1
            if lines > collapseLines { return true }
        }
        return false
    }

    /// The first `previewScalars` / `previewLines` of a turn's first block, cut at a line break or a space in the
    /// back half of the window (never inside a word when one is there), its washes clipped to what is kept; nil when
    /// the block already fits.
    static func preview(_ block: ReaderBlock) -> ReaderBlock? {
        let scalars = ScalarText(block.text)
        guard var cut = previewEnd(scalars) else { return nil }
        // Trailing space only: a leading trim would move every wash.
        while cut > 0, CharacterSet.whitespacesAndNewlines.contains(scalars.scalars[cut - 1]) { cut -= 1 }
        let washes = block.washes.compactMap { wash -> ReaderWash? in
            let hi = min(wash.range.upperBound, cut)
            return hi > wash.range.lowerBound ? ReaderWash(range: wash.range.lowerBound..<hi, style: wash.style) : nil
        }
        let text = scalars.slice(0, cut) + "…"
        return ReaderBlock(index: block.index, chunk: block.chunk, role: block.role, speaker: block.speaker,
                           mark: block.mark, time: block.time, text: text, contentStart: block.contentStart,
                           washes: washes)
    }

    /// Where a preview ends (a scalar offset), or nil when the whole text is within the preview's limits.
    static func previewEnd(_ scalars: ScalarText) -> Int? {
        let s = scalars.scalars
        let limit = min(s.count, previewScalars)
        var lines = 1
        for i in 0..<limit where s[i] == "\n" {
            lines += 1
            // The line that would be one too many starts here: cut before it.
            if lines > previewLines { return i }
        }
        guard limit < s.count else { return nil }
        let window = (limit / 2)..<limit
        if let nl = window.reversed().first(where: { s[$0] == "\n" }) { return nl }
        if let sp = window.reversed().first(where: { s[$0] == " " }) { return sp }
        return limit
    }

    // MARK: Words

    /// A gate-B2 line without its bracket: "[Cicada: 12 turns … were not kept]" → "12 turns … were not kept".
    /// The stored stamps ("from 2026-10-19T09:40:00Z to …") read as clock times, as every other time in the chat is.
    static func gapWords(_ text: String, locale: Locale = .autoupdatingCurrent,
                         timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if words.hasPrefix("[Cicada: ") { words.removeFirst("[Cicada: ".count) }
        if words.hasSuffix("]") { words.removeLast() }
        words = words.split(separator: " ", omittingEmptySubsequences: false).map { word -> String in
            guard word.contains("T"), ReaderTime.instant(String(word), timeZone: timeZone) != nil,
                  let clock = ReaderTime.label(String(word), locale: locale, timeZone: timeZone) else { return String(word) }
            return clock
        }.joined(separator: " ")
        guard let first = words.first else { return Copy.Provenance.notCaptured }
        return first.uppercased() + words.dropFirst()
    }

    /// A day separator's words, relative to `now` and computed when read (DR-58): "Today", "Yesterday", a weekday
    /// within the week, then "Sep 3", with the year once it is not this year's.
    static func dayLabel(_ date: Date, now: Date, locale: Locale = .autoupdatingCurrent,
                         timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        calendar.locale = locale
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: date),
                                           to: calendar.startOfDay(for: now)).day ?? Int.max
        if days == 0 { return Copy.Provenance.today }
        if days == 1 { return Copy.Provenance.yesterday }
        var style: Date.FormatStyle
        if days > 1 && days < 7 {
            style = Date.FormatStyle().weekday(.wide)
        } else if calendar.component(.year, from: date) == calendar.component(.year, from: now) {
            style = Date.FormatStyle().weekday(.abbreviated).month(.abbreviated).day()
        } else {
            style = Date.FormatStyle().month(.abbreviated).day().year()
        }
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }
}

// MARK: - Keyboard

/// ↑ / ↓, the page keys, Home / End and ⌘↑ / ⌘↓ in a chat (DR-60, DR-68): which row to bring into view. The Reader
/// keeps a cursor on the row the keys last showed; nothing here animates.
enum ReaderChatKeys {
    enum Move: Equatable { case previous, next, pageUp, pageDown, first, last }
    /// Rows a page key moves.
    static let page = 5

    /// The target row's position among `count` rows from `current` (nil: the Reader has not moved yet, so the
    /// newest is where it is), and the edge it lines up with.
    static func target(_ move: Move, from current: Int?, count: Int) -> (index: Int, alignsTop: Bool)? {
        guard count > 0 else { return nil }
        let here = current ?? count - 1
        switch move {
        case .first: return (0, true)
        case .last: return (count - 1, false)
        case .previous: return (max(here - 1, 0), true)
        case .next: return (min(here + 1, count - 1), false)
        case .pageUp: return (max(here - page, 0), true)
        case .pageDown: return (min(here + page, count - 1), false)
        }
    }
}
