import Foundation

/// How a quote reads where it was cut (`evidence_window`): the words go on in the source.
enum QuoteCut {
    static let before = "… "
    static let after = " …"
}

/// The evidence a question shows (owner 2026-11-24: "chats should appear as chat bubbles and the name … should be
/// highlighted"), pure so a test can read it without a view. One door for every kind of question that has a cause:
///
/// - **a conversation** (the server sent its turns, `InboxCause.turns`) is drawn by the Reader's own chat rows — the
///   same bubbles, sides, faces and times (`ReaderChat.rows`), built over the turns the server cut around the mention
///   and never a second renderer; a long turn was cut at a sentence and says so with "…";
/// - **anything else** (a note, an article, a transcript line) is a quote in whole sentences (`QuoteSegments`);
/// - **no cause** shows nothing; the card says `[ no source recorded ]` in its source line, as before.
///
/// A name found by searching is washed and semibold (`.found`); only a G118 span the claim quoted is underlined.
enum QuestionEvidence {
    struct Chat: Equatable {
        /// The Reader's rows over the cause's turns, with no day separators (the source line names the day).
        let rows: [ReaderChat.Row]
        /// The turn holding the mention: the rows read primary there and secondary elsewhere, as in the Reader.
        let focusTurn: Int?
        /// The Messages chat the sitting belongs to, for the other side's picture.
        let messagesChat: String?
        /// Every word shown, for the digits a number token stands for.
        let text: String
    }

    enum Shape: Equatable {
        case chat(Chat)
        case quote([CitedSpan.Segment])
        case none
    }

    static func of(_ item: InboxItem, links: PageLinkIndex = .empty) -> Shape {
        guard item.hasCause, let cause = item.cause else { return .none }
        if let chat = chat(cause) { return .chat(chat) }
        if let segments = QuoteSegments.of(item, links: links) { return .quote(segments) }
        return .none
    }

    /// The cause as the Reader's chat rows, or nil when the server sent no turns or the Reader would not call it a chat.
    static func chat(_ cause: InboxCause, timeZone: TimeZone = .autoupdatingCurrent) -> Chat? {
        guard !cause.turns.isEmpty, !cause.excerpt.isEmpty else { return nil }
        let turns = cause.turns.map {
            EpisodeTurn(index: $0.index, start: $0.start, contentStart: $0.contentStart, end: $0.end, role: $0.role,
                        marker: $0.marker, speaker: $0.speaker, ts: $0.ts, speakerKind: $0.speakerKind)
        }
        var doc = EpisodeText(episode: cause.episodeId ?? "", text: cause.excerpt, title: cause.conversationTitle ?? "",
                              timestamp: cause.timestamp, harness: cause.harness, origin: cause.origin,
                              conversationId: cause.conversationId, turns: turns, source: cause.source,
                              correspondent: cause.correspondent)
        // What the Reader's rows read from the document to attribute a turn: a relayed person's turn is headed
        // "relayed by <app>" and a meeting names every run. Whatever the rows need, the card's document carries.
        doc.relay = cause.relay
        doc.meeting = cause.meeting
        guard ReaderChat.isChat(doc) else { return nil }
        let scalars = ScalarText(doc.text)
        let marks: [Range<Int>] = cause.mentionOffsets.compactMap { pair in
            guard pair.count == 2, pair[0] >= 0, pair[0] < pair[1], pair[1] <= scalars.count else { return nil }
            return pair[0]..<pair[1]
        }
        let asserted = cause.spanKind == "asserted"
        var blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: marks.first,
                                         focusStyle: asserted ? .focus : .found, others: Array(marks.dropFirst()),
                                         othersStyle: .found, timeZone: timeZone)
        blocks = edged(blocks, cuts: Dictionary(uniqueKeysWithValues: cause.turns.map { ($0.index, ($0.cutBefore, $0.cutAfter)) }))
        // The whole window is on screen: nothing folds behind "Show more" (the server capped every turn already).
        var rows = ReaderChat.rows(blocks: blocks, doc: doc, keepOpen: Set(turns.map(\.index)), namesOtherSide: true,
                                   timeZone: timeZone)
        rows.removeAll { if case .day = $0.kind { true } else { false } }
        if let first = rows.first {
            rows[0] = ReaderChat.Row(id: first.id, kind: first.kind, gap: .none)
        }
        guard !rows.isEmpty else { return nil }
        // The question's own mention (the first), not the first place its words or the other side's name are said.
        let focusTurn = marks.first.flatMap { m in cause.turns.first { $0.contentStart <= m.lowerBound && m.lowerBound < $0.end }?.index }
        return Chat(rows: rows, focusTurn: focusTurn,
                    messagesChat: ReaderChat.messagesChat(doc), text: cause.excerpt)
    }

    /// A turn the server cut starts or ends with "…" in its bubble (the washes move with the words).
    static func edged(_ blocks: [ReaderBlock], cuts: [Int: (Bool, Bool)]) -> [ReaderBlock] {
        var last: [Int: Int] = [:]
        for block in blocks { last[block.index] = max(last[block.index] ?? 0, block.chunk) }
        return blocks.map { block in
            guard let (before, after) = cuts[block.index] else { return block }
            let head = before && block.chunk == 0
            let tail = after && block.chunk == last[block.index]
            guard head || tail else { return block }
            let lead = head ? QuoteCut.before : ""
            let shift = lead.unicodeScalars.count
            var edited = ReaderBlock(
                index: block.index, chunk: block.chunk, role: block.role, speaker: block.speaker, mark: block.mark,
                time: block.time, text: lead + block.text + (tail ? QuoteCut.after : ""),
                contentStart: block.contentStart,
                washes: block.washes.map { ReaderWash(range: ($0.range.lowerBound + shift)..<($0.range.upperBound + shift),
                                                      style: $0.style) })
            edited.showsTurnNumber = block.showsTurnNumber
            return edited
        }
    }
}
