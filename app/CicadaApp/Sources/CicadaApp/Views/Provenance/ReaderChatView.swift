import SwiftUI

/// The Reader's chat layout (owner, 2026-10-19), drawn from `ReaderChat.rows`. A `ForEach` body, flattened into the
/// Reader's own `LazyVStack` so a 500-turn session or a 47k-character export realises only what is on screen.
///
/// D's grammar (DESIGN_RULES §9, 2026-10-19, amended 2026-10-20): the person's turns sit on the right in a neutral
/// `chatBubbleFill` bubble — never the accent (DR-5), no shadow and no ring (DR-9, DR-10); the other party's sit on the
/// left in a quieter `chatBubbleOtherFill` bubble with the resting ring (DR-9), both in the quote face (DR-18); a
/// message holding a cited passage says so with a quiet marker beside its bubble ("Cited", a 2 pt bar; in words for
/// VoiceOver), never with a fill that reads as a selection; day separators and Cicada's gap note are centred words, never a
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
    /// 0…1 — the brief ring on the message a pointer jump landed on (`ReaderColumn.citedEmphasis`); a keyboard jump
    /// leaves it 0 (DR-60).
    var emphasis: Double = 0
    var onToggle: (Int) -> Void = { _ in }
    /// A reply's line was clicked: bring its target into view.
    var onJump: (ReaderBlock.Key) -> Void = { _ in }

    var body: some View {
        // Identified by the id landing, the rotors and `scrollPosition(id:)` read, so the column can say which row is
        // at its top.
        ForEach(rows, id: \.scrollID) { row in
            ReaderChatRowView(row: row, landingTurn: landingTurn, revealed: revealed, messagesChat: messagesChat,
                              emphasis: emphasis, onToggle: onToggle, onJump: onJump)
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
    var emphasis: Double = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ReaderChatRows(rows: rows, landingTurn: landingTurn, revealed: revealed, messagesChat: messagesChat,
                           emphasis: emphasis)
        }
    }
}

private struct ReaderChatRowView: View {
    let row: ReaderChat.Row
    let landingTurn: Int?
    let revealed: Bool
    let messagesChat: String?
    let emphasis: Double
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
            ReaderChatMessageView(message: message, ink: ink(for: message.block), revealed: revealed,
                                  messagesChat: messagesChat, emphasis: emphasis, onJump: onJump)
        case let .toggle(turn, side, expanded):
            HStack(spacing: 0) {
                if side == .person { Spacer(minLength: 0) }
                TextButton(title: expanded ? Copy.Provenance.showLess : Copy.Provenance.showMore,
                           help: expanded ? Copy.Provenance.showLessHelp : Copy.Provenance.showMoreHelp,
                           inline: true) { onToggle(turn) }
                    // The text button's own inset, pulled back so its words align with the bubble's edge.
                    .padding(side == .person ? .trailing : .leading, -CicadaTheme.scaled(6))
                if side == .other { Spacer(minLength: 0) }
            }
            .padding(.top, CicadaTheme.scaled(2))
        }
    }

    /// The Reader's one emphasis rule: the landing turn primary, the rest secondary; with nothing landed on, all primary.
    private func ink(for block: ReaderBlock) -> Color {
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

struct ReaderChatMessageView: View {
    let message: ReaderChat.Message
    let ink: Color
    let revealed: Bool
    let messagesChat: String?
    let emphasis: Double
    let onJump: (ReaderBlock.Key) -> Void

    /// The room a bubble always leaves on its far side, so the two sides never meet — and where its cited marker sits.
    static let otherSideRoom: CGFloat = 48
    static let bubblePadding = EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12)
    /// The cited marker: a 2 pt bar the height of a line, `markerGap` from the bubble, its word beyond it.
    static let markerBar: CGFloat = 2
    static let markerGap: CGFloat = 6
    /// The landed message's brief ring (pointer jumps only), at full emphasis.
    static let emphasisRing: CGFloat = 1.5

    private var side: ReaderChat.Side { message.side }
    private var mark: ReaderChat.CitedMark? { ReaderChat.citedMark(message.block) }

    var body: some View {
        VStack(alignment: side == .person ? .trailing : .leading, spacing: CicadaTheme.spacingXS) {
            if let header = message.header {
                ReaderChatHeader(header: header, side: side, messagesChat: messagesChat)
            }
            if let extras = message.extras {
                above(extras)
            }
            if !message.block.text.isEmpty {
                bubble
            }
            if let extras = message.extras {
                below(extras)
            }
        }
        .frame(maxWidth: .infinity, alignment: side == .person ? .trailing : .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(ReaderChat.accessibilityLabel(message))
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

    /// Each side's bubble hugs its words and leaves `otherSideRoom` on its far side; a long message's pieces read as
    /// one bubble (square corners where they meet, and the ring drawn open there).
    private var bubble: some View {
        let top = message.piece == .whole || message.piece == .first
        let bottom = message.piece == .whole || message.piece == .last
        let shape = CicadaTheme.chatBubble(roundTop: top, roundBottom: bottom)
        let words = CitedPassage(segments: ReaderText.segments(message.block), color: ink, reveal: revealed ? 1 : 0,
                                 fillsWidth: false)
            .padding(.horizontal, CicadaTheme.scaled(Self.bubblePadding.leading))
            .padding(.top, top ? CicadaTheme.scaled(Self.bubblePadding.top) : 0)
            .padding(.bottom, bottom ? CicadaTheme.scaled(Self.bubblePadding.bottom) : 0)
            .background(shape.fill(side == .person ? CicadaTheme.chatBubbleFill : CicadaTheme.chatBubbleOtherFill))
            .overlay {
                // DR-9 — the other party's bubble is lifted by the resting ring; the landed message's emphasis is a
                // ring too, fading (never the accent, never a shadow). Drawn past an open end and clipped, so a long
                // message's pieces show no seam.
                ZStack {
                    if side == .other {
                        shape.strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1)
                    }
                    if mark == .current, emphasis > 0 {
                        shape.strokeBorder(CicadaTheme.textTertiary.opacity(emphasis), lineWidth: Self.emphasisRing)
                    }
                }
                .padding(.top, top ? 0 : -Self.emphasisRing * 2)
                .padding(.bottom, bottom ? 0 : -Self.emphasisRing * 2)
            }
            .clipShape(Rectangle())
        // The room is the same with or without a marker, so a cited bubble is never narrower than its neighbours:
        // the marker takes its slot out of the room, against the bubble.
        let room = CicadaTheme.scaled(Self.otherSideRoom)
        let slot = room - CicadaTheme.scaled(Self.markerGap)
        return HStack(alignment: .top, spacing: 0) {
            if side == .person {
                if let mark {
                    Spacer(minLength: 0)
                    marker(mark, slot: slot, top: top)
                    Spacer(minLength: room - slot).frame(width: room - slot)
                } else {
                    Spacer(minLength: room)
                }
            }
            words
            if side == .other {
                if let mark {
                    Spacer(minLength: room - slot).frame(width: room - slot)
                    marker(mark, slot: slot, top: top)
                    Spacer(minLength: 0)
                } else {
                    Spacer(minLength: room)
                }
            }
        }
    }

    private func marker(_ mark: ReaderChat.CitedMark, slot: CGFloat, top: Bool) -> some View {
        ReaderCitedMarker(mark: mark, side: side)
            .frame(minWidth: slot, alignment: side == .person ? .trailing : .leading)
            // Level with the bubble's first line.
            .padding(.top, CicadaTheme.scaled(top ? Self.bubblePadding.top + 3 : 3))
    }
}

/// "Cited ▍" beside a bubble (owner, 2026-10-20): the bar against the bubble, the word beyond it, both on the bubble's
/// inner side, in the room it always leaves. The current span's bar is the accent (DR-5 use 4, the cited span); another
/// cited span's is the quote rule's neutral (DR-18). The word is tertiary meta text on the pane, never on the bubble
/// (DR-2). Hidden from VoiceOver here: the message's own label says it first (`ReaderChat.accessibilityLabel`).
struct ReaderCitedMarker: View {
    let mark: ReaderChat.CitedMark
    let side: ReaderChat.Side

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            if side == .person { word }
            Rectangle()
                .fill(mark == .current ? CicadaTheme.accent : CicadaTheme.quoteRule)
                .frame(width: ReaderChatMessageView.markerBar, height: CicadaTheme.scaled(14))
            if side == .other { word }
        }
        .fixedSize()
        .help(Copy.Provenance.citedMarkerHelp)
        .accessibilityHidden(true)
    }

    private var word: some View {
        Text(Copy.Provenance.citedMarker)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
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
