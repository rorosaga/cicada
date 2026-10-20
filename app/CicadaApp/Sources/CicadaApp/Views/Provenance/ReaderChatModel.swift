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
    /// calendar entry) with at least one turn a conversation marker WROTE — `user:`/`human:`, `assistant:`/`ai:` or
    /// `speaker:<name>:`. The role alone never makes a chat: an episode that declares whose words it holds
    /// (`evidence_kind`, R-LS7 — an agent-written folder file, a memory export entry) has every turn's role forced,
    /// marker or not, and a note with no marker is one block of prose.
    static func isChat(_ doc: EpisodeText) -> Bool {
        guard !doc.isPage, !doc.isPageRead, doc.watch == nil, EvidenceSpeaker.sourceSpeaker(doc.origin) == nil else {
            return false
        }
        return doc.turns.contains { conversationMarker($0.marker) }
    }

    /// The written words that open a conversation's turn (`evidence._TURN_RE`'s role words and the note-taker's
    /// `speaker:` family); an attachment, a video line or Cicada's gap are not a conversation by themselves.
    static func conversationMarker(_ marker: String?) -> Bool {
        guard let m = marker?.lowercased() else { return false }
        return ["user", "human", "assistant", "ai"].contains(m) || m.hasPrefix("speaker")
    }

    /// Which side the WRITTEN marker puts a turn on, or nil when the turn has none (a block before the first marker,
    /// a reply resumed after a gap). The marker, not the role: a relayed conversation (ruling 32) forces every role to
    /// `assistant` while keeping each line's marker as written, so only the marker still says who spoke.
    static func markerSide(_ marker: String?) -> Side? {
        guard let m = marker?.lowercased(), m != "gap" else { return nil }
        return ["user", "human", "system", "unknown"].contains(m) ? .person : .other
    }

    /// The party a chat's header already names — its correspondent, else its agent with the latest turn's model, as
    /// `EvidenceSpeaker.turnSpeaker` would label that turn — so a run head does not say it again (DR-38).
    static func namedParty(_ doc: EpisodeText) -> String? {
        if let correspondent = doc.correspondent, !correspondent.isEmpty { return correspondent }
        guard let agent = EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin) else { return nil }
        return ModelNames.agentLine(agent: agent, harness: nil, model: doc.agent?.model, effort: doc.agent?.effort)
    }

    /// The turns that never fold: each one holding a cited or found span (any of its blocks — a quote in a long turn's
    /// third block keeps the whole turn open), and the turn a landing scrolls to, even when nothing there is washed
    /// (a stale quote, a name that was not found).
    static func keepOpen(blocks: [ReaderBlock], landing: ReaderBlock.Key?) -> Set<Int> {
        var open = Set(blocks.filter(\.holdsFocus).map(\.index))
        if let landing { open.insert(landing.turn) }
        return open
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
    enum Piece: Hashable {
        case whole, first, middle, last

        /// The extras this piece draws: the reply above the first, the chips and "Edited" under the last.
        func part(of extras: Extras) -> Extras? {
            var out = Extras()
            if self == .whole || self == .first { out.reply = extras.reply; out.forwardedFrom = extras.forwardedFrom }
            if self == .whole || self == .last {
                out.reactions = extras.reactions
                out.attachments = extras.attachments
                out.edited = extras.edited
            }
            return out.isEmpty ? nil : out
        }
    }

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
        /// What made the turn part of a conversation (2026-10-20): the reply line above its first piece, the chips
        /// and "Edited" under its last. Nil when the turn has none, or on a middle piece.
        var extras: Extras? = nil
    }

    /// A reply's line above the bubble: who it answers and the start of what they said; `target` is the block a
    /// tap scrolls to, nil for a reply to a message this document does not hold.
    struct Reply: Hashable {
        let target: ReaderBlock.Key?
        let words: String
    }

    /// One chip per emoji under the bubble, the people who chose it said on hover.
    struct ReactionChip: Hashable {
        let emoji: String
        let count: Int
        let help: String
    }

    struct Extras: Hashable {
        var reply: Reply? = nil
        var forwardedFrom: String? = nil
        var reactions: [ReactionChip] = []
        var attachments: [String] = []
        var edited = false
        var isEmpty: Bool { reply == nil && forwardedFrom == nil && reactions.isEmpty && attachments.isEmpty && !edited }
    }

    struct Row: Identifiable, Hashable {
        enum ID: Hashable {
            case day(Int)
            case block(ReaderBlock.Key)
            case toggle(Int)
            /// An unsent message: before the turn with this index, the n-th there.
            case unsent(Int, Int)
        }
        enum Kind: Hashable {
            /// "Today", "Yesterday", "Monday", "Sep 3" — computed when read (DR-58).
            case day(String)
            /// G110 gate B2 — Cicada's own line where a conversation's middle (or part of a reply) was not kept.
            case gap(ReaderBlock, words: String)
            case message(Message)
            /// "Show more" / "Show less" under a long turn.
            case toggle(turn: Int, side: Side, expanded: Bool)
            /// "You unsent a message" — where it was, never its words (2026-10-20).
            case unsent(String)
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
        var lastOtherName: String? = namedParty(doc)
        var lastPersonName: String?
        // Ruling 32: a relayed person's turn is on their side but is not "You" — the model relayed it.
        let relayed = doc.relay.map { relay in
            Copy.Provenance.relayedBy(relay.label ?? EvidenceSpeaker.agentName(harness: doc.harness, origin: nil))
        }
        let unsentBefore = Dictionary(grouping: doc.unsent, by: \.before)
        func emitUnsent(before index: Int) {
            for (n, gone) in (unsentBefore[index] ?? []).enumerated() {
                out.append(Row(id: .unsent(index, n), kind: .unsent(Copy.Provenance.unsent(partyName(gone.speaker, doc: doc))),
                               gap: out.isEmpty ? .none : .newRun))
                last = nil
            }
        }
        for (position, index) in order.enumerated() {
            guard var turnBlocks = pieces[index], let head = turnBlocks.first else { continue }
            let turn = turnsByIndex[index]
            var extras = turn?.extras.map { chatExtras($0, doc: doc, pieces: pieces) }
            if extras?.isEmpty == true { extras = nil }
            if let attachments = turn?.extras?.attachments, !attachments.isEmpty, let tail = turnBlocks.last,
               let cut = withoutAttachmentNames(tail, count: attachments.count) {
                // The words keep "[image: name]" (Sleep reads them); the chip says it here, so the bubble does not.
                turnBlocks[turnBlocks.count - 1] = cut
            }
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
            emitUnsent(before: index)

            if head.role == "gap" {
                // Cicada's note sits between the turns it separates; a reply resumed after it reads on as the same run.
                for block in turnBlocks {
                    out.append(Row(id: .block(block.id), kind: .gap(block, words: gapWords(block.text, locale: locale, timeZone: timeZone)),
                                   gap: out.isEmpty ? .none : .newRun))
                }
                continue
            }

            let side = markerSide(turn?.marker) ?? (turn?.marker == nil && position > 0 ? last?.side : nil)
                ?? side(of: head)
            let speaker = side == .person ? (relayed ?? head.speaker) : head.speaker
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
            let foldable = isLong(turnBlocks) && !keepOpen.contains(index)
            let gapAbove: Gap = out.isEmpty ? .none : (startsRun ? .newRun : .inRun)
            if foldable && !open, let preview = preview(turnBlocks[0]) {
                out.append(Row(id: .block(head.id), kind: .message(Message(
                    block: preview, side: side, header: header, piece: .whole, speaker: speaker, time: head.time,
                    folded: true, extras: extras)), gap: gapAbove))
            } else {
                for (n, block) in turnBlocks.enumerated() {
                    let piece: Piece = turnBlocks.count == 1 ? .whole
                        : n == 0 ? .first : n == turnBlocks.count - 1 ? .last : .middle
                    out.append(Row(id: .block(block.id), kind: .message(Message(
                        block: block, side: side, header: n == 0 ? header : nil, piece: piece, speaker: speaker,
                        time: head.time, folded: false, extras: extras.flatMap { piece.part(of: $0) })),
                                   gap: n == 0 ? gapAbove : .none))
                }
            }
            if foldable {
                out.append(Row(id: .toggle(index), kind: .toggle(turn: index, side: side, expanded: open), gap: .none))
            }
        }
        // An unsent message after the last turn.
        emitUnsent(before: (order.last ?? 0) + 1)
        return out
    }

    // MARK: Extras (2026-10-20)

    /// Who a turn marker names, as the chat says it: "You", the chat's correspondent or agent, a speaker's label.
    static func partyName(_ marker: String, doc: EpisodeText) -> String {
        if marker == "user" { return Copy.you }
        if let named = namedParty(doc) { return named }
        if marker.hasPrefix("speaker:") {
            let label = marker.dropFirst("speaker:".count).replacingOccurrences(of: "-", with: " ")
            return label.isEmpty ? Copy.Provenance.chatSomeone : label.capitalized
        }
        return EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin) ?? Copy.Provenance.chatSomeone
    }

    /// The most of a reply's target the line above the bubble quotes.
    static let replyExcerpt = 60

    static func chatExtras(_ extras: EpisodeTurnExtras, doc: EpisodeText, pieces: [Int: [ReaderBlock]]) -> Extras {
        var out = Extras()
        if let target = extras.replyTo, let block = pieces[target]?.first {
            let who = doc.turns.first { $0.index == target }.map { partyName($0.marker ?? "user", doc: doc) }
                ?? block.speaker
            out.reply = Reply(target: block.id, words: Copy.Provenance.replyingTo(who == Copy.you ? "you" : who,
                                                                                 excerpt: excerpt(block.text)))
        } else if extras.replyTo != nil || extras.replyElsewhere {
            out.reply = Reply(target: nil, words: Copy.Provenance.earlierMessage)
        }
        out.forwardedFrom = extras.forwardedFrom.map(Copy.Provenance.forwardedFrom)
        var byEmoji: [(emoji: String, who: [String])] = []
        for reaction in extras.reactions {
            let emoji = reaction.emoji ?? defaultEmoji[reaction.kind] ?? "\u{2022}"
            let who = partyName(reaction.by, doc: doc)
            if let i = byEmoji.firstIndex(where: { $0.emoji == emoji }) { byEmoji[i].who.append(who) }
            else { byEmoji.append((emoji, [who])) }
        }
        out.reactions = byEmoji.map { ReactionChip(emoji: $0.emoji, count: $0.who.count,
                                                   help: Copy.Provenance.reacted($0.who, emoji: $0.emoji)) }
        out.attachments = extras.attachments.map {
            Copy.Provenance.attachment(kind: $0.kind, name: $0.name, size: $0.size, generated: $0.generated)
        }
        if let runs = extras.codeRuns, runs > 0 { out.attachments.append(Copy.Provenance.ranCode(runs)) }
        out.edited = extras.edited
        return out
    }

    static let defaultEmoji = ["love": "\u{2764}\u{FE0F}", "like": "\u{1F44D}", "dislike": "\u{1F44E}",
                               "laugh": "\u{1F602}", "emphasize": "\u{203C}\u{FE0F}", "question": "\u{2753}"]

    /// The first `replyExcerpt` characters of a target's words, cut at a space, on one line.
    static func excerpt(_ text: String) -> String {
        let line = text.split(whereSeparator: \.isNewline).joined(separator: " ")
        guard line.count > replyExcerpt else { return line }
        let head = line.prefix(replyExcerpt)
        let cut = head.lastIndex(of: " ").map { head[..<$0] } ?? head
        return cut.trimmingCharacters(in: .whitespaces.union(CharacterSet(charactersIn: ".,;:"))) + "\u{2026}"
    }

    /// A Messages turn's block without the trailing "[image: name]" words its attachments left, when they are there
    /// (at most `count` of them); nil when there is nothing to cut. Washes are clipped to what stays.
    static func withoutAttachmentNames(_ block: ReaderBlock, count: Int) -> ReaderBlock? {
        let scalars = Array(block.text.unicodeScalars)
        var end = scalars.count
        var cut = 0
        while cut < count, end > 0, scalars[end - 1] == "]" {
            guard let open = scalars[..<end].lastIndex(of: "[") else { break }
            let token = String(String.UnicodeScalarView(scalars[open..<end]))
            guard token.range(of: #"^\[(image|video|audio|file): [^\[\]]*\]$"#, options: .regularExpression) != nil else {
                break
            }
            end = open
            while end > 0, scalars[end - 1] == " " { end -= 1 }
            cut += 1
        }
        guard cut > 0 else { return nil }
        let washes = block.washes.compactMap { wash -> ReaderWash? in
            let hi = min(wash.range.upperBound, end)
            return hi > wash.range.lowerBound ? ReaderWash(range: wash.range.lowerBound..<hi, style: wash.style) : nil
        }
        return ReaderBlock(index: block.index, chunk: block.chunk, role: block.role, speaker: block.speaker,
                           mark: block.mark, time: block.time,
                           text: String(String.UnicodeScalarView(scalars[0..<end])),
                           contentStart: block.contentStart, washes: washes)
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

    /// The first `previewScalars` / `previewLines` of a turn's first block, its washes clipped to what is kept; nil
    /// when the block already fits. Cut at a line break, the preview simply stops there (the line is whole); cut
    /// mid-line, at a space where one is in the back half of the window, it drops the trailing space and punctuation
    /// and ends in "…" — never ".…".
    static func preview(_ block: ReaderBlock) -> ReaderBlock? {
        let scalars = ScalarText(block.text)
        guard let end = previewEnd(scalars) else { return nil }
        let s = scalars.scalars
        let atLineBreak = end < s.count && (s[end] == "\n" || s[end] == "\r")
        var cut = end
        // Trailing only: a leading trim would move every wash.
        let trailing = atLineBreak ? CharacterSet.whitespacesAndNewlines
            : CharacterSet.whitespacesAndNewlines.union(CharacterSet(charactersIn: ".,;:…"))
        while cut > 0, trailing.contains(s[cut - 1]) { cut -= 1 }
        let washes = block.washes.compactMap { wash -> ReaderWash? in
            let hi = min(wash.range.upperBound, cut)
            return hi > wash.range.lowerBound ? ReaderWash(range: wash.range.lowerBound..<hi, style: wash.style) : nil
        }
        let text = scalars.slice(0, cut) + (atLineBreak ? "" : "…")
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

/// ↑ / ↓, the page keys, Home / End and ⌘↑ / ⌘↓ in a chat (DR-60, DR-68): which row to bring into view. Every move
/// is relative to the row at the top of the column as it is now — the scroll view reports it (`scrollPosition(id:)`),
/// so a trackpad scroll moves the keys' starting point too — and lines its target up with the top, except the newest,
/// which lines up with the bottom. Nothing here animates.
enum ReaderChatKeys {
    enum Move: Equatable { case previous, next, pageUp, pageDown, first, last }
    /// Rows a page key moves.
    static let page = 5

    /// The target row among `count` rows, from the row at the top (`top`; nil before the scroll view has said, when
    /// the chat has just opened at its newest row), and whether it lines up with the top.
    static func target(_ move: Move, top: Int?, count: Int) -> (index: Int, alignsTop: Bool)? {
        guard count > 0 else { return nil }
        let here = min(max(top ?? count - 1, 0), count - 1)
        switch move {
        case .first: return (0, true)
        case .last: return (count - 1, false)
        case .previous: return (max(here - 1, 0), true)
        case .next: return (min(here + 1, count - 1), true)
        case .pageUp: return (max(here - page, 0), true)
        case .pageDown: return (min(here + page, count - 1), true)
        }
    }
}
