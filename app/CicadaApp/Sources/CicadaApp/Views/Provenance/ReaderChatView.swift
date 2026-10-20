import SwiftUI

/// The Reader's chat layout (owner, 2026-10-19), drawn from `ReaderChat.rows`. A `ForEach` body, flattened into the
/// Reader's own `LazyVStack` so a 500-turn session or a 47k-character export realises only what is on screen.
///
/// D's grammar (DESIGN_RULES §9, 2026-10-19): the person's turns sit on the right in a neutral `chatBubbleFill` bubble
/// — never the accent (DR-5), no shadow and no ring (DR-9, DR-10); the other party's read on the left as plain text in
/// the quote face (DR-18), like a reply in a chat app; day separators and Cicada's gap note are centred words, never a
/// rule (DR-11); the face or mark, the name and a time are said once per run (DR-38, DR-52, DR-57); a long message
/// folds behind a text button (DR-39, DR-40). Every passage is a `CitedPassage`, so the wash and the underline are
/// exactly the document view's.
///
/// What made it a conversation (2026-10-20, `turn_extras`): a reply's line sits above the bubble and is a text button
/// to its target (DR-40); reactions and attachments are `Tag`s under it (DR-44, the one pill), who reacted said on
/// hover (`.help`); "Edited" and "You unsent a message" are words (DR-11 for the centred one, DR-38: nothing repeats
/// the bubble). A jump never animates (DR-60).
struct ReaderChatRows: View {
    let rows: [ReaderChat.Row]
    /// The landing turn: it reads in the primary colour and the rest secondary, as in the document view. Nil when the
    /// Reader opened on no quote — then every message reads primary.
    let landingTurn: Int?
    let revealed: Bool
    /// The Messages chat this sitting belongs to, for its picture.
    var messagesChat: String? = nil
    var onToggle: (Int) -> Void = { _ in }
    /// A reply's line was clicked: bring its target into view.
    var onJump: (ReaderBlock.Key) -> Void = { _ in }

    var body: some View {
        // Identified by the id landing, the rotors and `scrollPosition(id:)` read, so the column can say which row is
        // at its top.
        ForEach(rows, id: \.scrollID) { row in
            ReaderChatRowView(row: row, landingTurn: landingTurn, revealed: revealed, messagesChat: messagesChat,
                              onToggle: onToggle, onJump: onJump)
                .padding(.top, Self.space(row.gap))
                .id(row.scrollID)
        }
    }

    static func space(_ gap: ReaderChat.Gap) -> CGFloat {
        switch gap {
        case .none: 0
        case .inRun: CicadaTheme.scaled(4)
        case .newRun: CicadaTheme.scaled(16)
        case .section: CicadaTheme.scaled(24)
        }
    }
}

/// The rows in a plain stack — what the tests and the offscreen snapshots measure.
struct ReaderChatView: View {
    let rows: [ReaderChat.Row]
    let landingTurn: Int?
    let revealed: Bool
    var messagesChat: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ReaderChatRows(rows: rows, landingTurn: landingTurn, revealed: revealed, messagesChat: messagesChat)
        }
    }
}

private struct ReaderChatRowView: View {
    let row: ReaderChat.Row
    let landingTurn: Int?
    let revealed: Bool
    let messagesChat: String?
    let onToggle: (Int) -> Void
    let onJump: (ReaderBlock.Key) -> Void

    var body: some View {
        switch row.kind {
        case let .day(label):
            centred(label)
                .accessibilityAddTraits(.isHeader)
        case let .unsent(words):
            centred(words)
        case let .gap(_, words):
            centred(words)
                .accessibilityLabel("\(Copy.Provenance.notCaptured): \(words)")
        case let .message(message):
            ReaderChatMessageView(message: message, emphasis: emphasis(for: message.block), revealed: revealed,
                                  messagesChat: messagesChat, onJump: onJump)
        case let .toggle(turn, side, expanded):
            HStack(spacing: 0) {
                if side == .person { Spacer(minLength: 0) }
                TextButton(title: expanded ? Copy.Provenance.showLess : Copy.Provenance.showMore,
                           help: expanded ? Copy.Provenance.showLessHelp : Copy.Provenance.showMoreHelp,
                           inline: true) { onToggle(turn) }
                    // The text button's own inset, pulled back so its words align with the message's edge.
                    .padding(side == .person ? .trailing : .leading, -CicadaTheme.scaled(6))
                if side == .other { Spacer(minLength: 0) }
            }
            .padding(.top, CicadaTheme.scaled(2))
        }
    }

    /// The Reader's one emphasis rule: the landing turn primary, the rest secondary; with nothing landed on, all primary.
    private func emphasis(for block: ReaderBlock) -> Color {
        guard let landingTurn else { return CicadaTheme.textPrimary }
        return block.index == landingTurn ? CicadaTheme.textPrimary : CicadaTheme.textSecondary
    }

    /// DR-11 — a separator is words in the middle of the column, not a line across it.
    private func centred(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity)
    }
}

private struct ReaderChatMessageView: View {
    let message: ReaderChat.Message
    let emphasis: Color
    let revealed: Bool
    let messagesChat: String?
    let onJump: (ReaderBlock.Key) -> Void

    /// The room a person's bubble always leaves on its left, so the two sides never meet.
    static let otherSideRoom: CGFloat = 48
    static let bubblePadding = EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12)

    var body: some View {
        VStack(alignment: message.side == .person ? .trailing : .leading, spacing: CicadaTheme.spacingXS) {
            if let header = message.header {
                ReaderChatHeader(header: header, side: message.side, messagesChat: messagesChat)
            }
            if let extras = message.extras {
                above(extras)
            }
            if !message.block.text.isEmpty {
                switch message.side {
                case .person: bubble
                case .other: passage(fills: true)
                }
            }
            if let extras = message.extras {
                below(extras)
            }
        }
        .frame(maxWidth: .infinity, alignment: message.side == .person ? .trailing : .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityWords)
    }

    private var accessibilityWords: String {
        var words = Copy.Provenance.chatLabel(speaker: message.speaker, time: message.time, text: message.block.text)
        if let extras = message.extras {
            let more = [extras.reply?.words, extras.forwardedFrom] + extras.attachments.map(Optional.some)
                + extras.reactions.map { Optional.some($0.help) } + [extras.edited ? Copy.Provenance.edited : nil]
            words += more.compactMap { $0 }.map { ". " + $0 }.joined()
        }
        return words
    }

    /// The reply's line (a text button to its target) and "Forwarded from …", above the words.
    @ViewBuilder
    private func above(_ extras: ReaderChat.Extras) -> some View {
        if let reply = extras.reply {
            if let target = reply.target {
                TextButton(title: reply.words, help: Copy.Provenance.replyHelp, inline: true) { onJump(target) }
                    .lineLimit(1)
                    .truncationMode(.tail)
                    // The text button's own inset, pulled back so its words align with the message's edge.
                    .padding(message.side == .person ? .trailing : .leading, -CicadaTheme.scaled(6))
            } else {
                meta(reply.words)
            }
        }
        if let forwarded = extras.forwardedFrom {
            meta(forwarded)
        }
    }

    /// Attachments, then reactions and "Edited", under the words — `Tag`s, the one pill (DR-44).
    @ViewBuilder
    private func below(_ extras: ReaderChat.Extras) -> some View {
        ForEach(Array(extras.attachments.enumerated()), id: \.offset) { _, words in
            Tag(text: words)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        if !extras.reactions.isEmpty || extras.edited {
            HStack(spacing: CicadaTheme.spacingXS) {
                ForEach(extras.reactions, id: \.self) { chip in
                    Tag(text: chip.count > 1 ? "\(chip.emoji) \(chip.count)" : chip.emoji)
                        .help(chip.help)
                        .accessibilityLabel(chip.help)
                }
                if extras.edited {
                    meta(Copy.Provenance.edited)
                }
            }
        }
    }

    private func meta(_ words: String) -> some View {
        Text(words)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
            .truncationMode(.tail)
    }

    private func passage(fills: Bool) -> some View {
        CitedPassage(segments: ReaderText.segments(message.block), color: emphasis, reveal: revealed ? 1 : 0,
                     fillsWidth: fills)
    }

    private var bubble: some View {
        let top = message.piece == .whole || message.piece == .first
        let bottom = message.piece == .whole || message.piece == .last
        return HStack(spacing: 0) {
            Spacer(minLength: CicadaTheme.scaled(Self.otherSideRoom))
            passage(fills: false)
                .padding(.horizontal, CicadaTheme.scaled(Self.bubblePadding.leading))
                .padding(.top, top ? CicadaTheme.scaled(Self.bubblePadding.top) : 0)
                .padding(.bottom, bottom ? CicadaTheme.scaled(Self.bubblePadding.bottom) : 0)
                .background(CicadaTheme.chatBubble(roundTop: top, roundBottom: bottom).fill(CicadaTheme.chatBubbleFill))
        }
    }
}

/// The head of a run: the other party's face or mark and name (the name only when it changed), and the run's time;
/// on the person's side the time alone, at the right.
private struct ReaderChatHeader: View {
    let header: ReaderChat.Header
    let side: ReaderChat.Side
    let messagesChat: String?

    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @Environment(Store.self) private var store: Store?

    static let avatarSize: CGFloat = 16

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingXS) {
            avatar
            if let name = header.name {
                Text(name)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
            }
            if let time = header.time {
                Text(header.name == nil ? time : "· " + time)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
        }
        .padding(side == .person ? .trailing : .leading, side == .person ? CicadaTheme.scaled(4) : 0)
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var avatar: some View {
        switch header.avatar {
        case let .mark(origin):
            OriginMark(origin: origin, size: CicadaTheme.scaled(Self.avatarSize))
        case let .face(name):
            // The chat's own picture in Messages (`MessageBubbles.face`'s precedence), else a monogram — nothing from
            // the web, and never a page found by name.
            let waiting = messagesChat.flatMap { id in watcher?.waiting.first { $0.conversation == id } }
            MessageBubbleFace(name: name, photo: messagesChat.flatMap { watcher?.cards[$0]?.thumbnail },
                              size: Self.avatarSize,
                              page: MessageBubbles.pagePicture(page: waiting?.page, nodes: store?.graph.value?.nodes ?? []),
                              shared: messagesChat.flatMap { watcher?.sharedPhotos[$0] })
        case .none:
            EmptyView()
        }
    }
}
