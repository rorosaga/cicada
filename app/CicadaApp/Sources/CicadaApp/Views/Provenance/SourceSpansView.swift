import AppKit
import Observation
import SwiftUI

/// ROR-16, G118 — the one way a source is drawn with its spans highlighted: a document (`EpisodeText`) and what to wash
/// in it (`ReaderPresentation` for the span landed on, `others` for the rest), scrolled to the words. Everything that opens
/// a citation goes through the Reader, and the Reader draws its text with this; a later surface (ROR-15's note in its own
/// layout) hosts it directly with `SourceSpansState` and `ReaderPresentation.spans`. With nothing to locate it draws the
/// source and says nothing about it. Text only: a medium with no text is a later `layout`, as a span's `at` leaves room
/// for it. It draws words and no pictures, so nothing a source names is ever loaded from the web (`storage.md`).
struct SourceSpansView<Pinned: View, Below: View>: View {
    @Bindable var state: SourceSpansState
    let doc: EpisodeText
    let scalars: ScalarText
    let presentation: ReaderPresentation
    var others: [Range<Int>] = []
    /// ROR-15: the note as Notes draws it, once it arrives; the same spans wash it. Nil draws the stored text.
    var note: NoteDocument? = nil
    /// Set while an in-place jump is what moved the column, and who asked (DR-60); nil on opening.
    var jump: LooksZoom.Trigger? = nil
    /// Above the scroll, never in it: landing moves the scroll, and a bar inside it would leave the screen.
    @ViewBuilder var pinned: () -> Pinned
    /// Under the words, in the same scroll (DR-30).
    @ViewBuilder var below: () -> Below

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let layout = state.layout(doc, scalars: scalars, presentation: presentation, others: others, note: note)
        let blocks = layout.blocks
        let landingBlock = layout.landingBlock
        // One rotor stop per cited turn, even when the words straddle two of
        // its chunks — the rotor names turns, not layout pieces.
        var citedTurns = Set<Int>()
        let citedBlocks = blocks.filter { $0.holdsFocus && citedTurns.insert($0.index).inserted }
        // A chat names a message by who and when; the document view by who and which turn.
        let citedStops: [RotorStop] = layout.chat.map { chat in
            chat.compactMap(Self.citedMessage).map(RotorStop.init(message:))
        } ?? citedBlocks.map(RotorStop.init(block:))
        let turnStops: [RotorStop] = layout.chat.map { chat in
            chat.compactMap(Self.turnStart).map(RotorStop.init(message:))
        } ?? blocks.filter(\.startsTurn).map(RotorStop.init(block:))
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                pinned()
                // A chat opens at its newest message, so what the banners say ("only the first part is shown", "the
                // words may have moved") is pinned here rather than left at the top of the history.
                if layout.chat != nil, !presentation.banners.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(presentation.banners, id: \.self) { ReaderBannerView(banner: $0) }
                    }
                    .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                    .padding(.bottom, CicadaTheme.spacingSM)
                }
                ScrollView {
                    // Spacing 0 so a long turn's chunks (`ReaderLayout.chunks`)
                    // read on as one text; the gap goes between turns instead.
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if layout.chat == nil {
                            ForEach(presentation.banners, id: \.self) { banner in
                                ReaderBannerView(banner: banner)
                                    .padding(.bottom, CicadaTheme.spacingMD)
                            }
                        }
                        if blocks.isEmpty {
                            Text(Copy.Provenance.empty)
                                .font(CicadaTheme.detailBodyFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        // Flattened into this lazy stack, so a 400,000-character
                        // conversation's chunks are still realised on demand.
                        if let chat = layout.chat {
                            ReaderChatRows(rows: chat, landingTurn: presentation.focus == nil ? nil : landingBlock?.turn,
                                           revealed: state.washVisible, messagesChat: ReaderChat.messagesChat(doc),
                                           emphasis: state.citedEmphasis,
                                           onToggle: { state.toggle($0) },
                                           onJump: { key in
                                               // A reply's target: one frame, never animated (DR-60).
                                               state.scroll(to: AnyHashable(key), alignsTop: true)
                                           })
                        } else if let rows = layout.noteRows {
                            NotePageRows(rows: rows, revealed: state.washVisible)
                        } else {
                            ReaderTurnRows(blocks: blocks, landingTurn: landingBlock?.turn, revealed: state.washVisible)
                        }
                        below()
                    }
                    .scrollTargetLayout()
                    .padding(.top, CicadaTheme.scaled(4))
                    .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                    .padding(.bottom, CicadaTheme.scaled(layout.chat == nil ? 72 : 24))
                }
                .scrollPosition(id: $state.topRow, anchor: .top)
                .accessibilityRotor("Cited passages") {
                    ForEach(citedStops, id: \.id) { stop in
                        AccessibilityRotorEntry(Text(stop.label), id: stop.id)
                    }
                }
                .accessibilityRotor("Turns") {
                    ForEach(turnStops, id: \.id) { stop in
                        AccessibilityRotorEntry(Text(stop.label), id: stop.id)
                    }
                }
                .onChange(of: state.landingToken, initial: true) { _, _ in
                    land(proxy: proxy, block: landingBlock, blocks: blocks, chat: layout.chat)
                }
                // The note's formatted page replaced the plain one under the same words: stay on them, no fade, no second
                // announcement (DR-60).
                .onChange(of: layout.noteRows != nil) { _, _ in
                    guard let landingBlock else { return }
                    Task { @MainActor in
                        await Task.yield()
                        Instant.run { proxy.scrollTo(landingBlock, anchor: .center) }
                    }
                }
                .onChange(of: state.keyScroll) { _, request in
                    // DR-60 — a key moves the column in one frame.
                    guard let request else { return }
                    Instant.run { proxy.scrollTo(request.id, anchor: request.alignsTop ? .top : .bottom) }
                }
            }
        }
    }

    private struct RotorStop {
        let id: ReaderBlock.Key
        let label: String
        init(block: ReaderBlock) {
            id = block.id
            // A note, a book or a save has no speaker: VoiceOver reads its place, never a blank stop.
            label = block.speaker.isEmpty ? Copy.Provenance.rotorPassage(block.index)
                : block.showsTurnNumber ? Copy.Provenance.rotorLabel(speaker: block.speaker, turn: block.index)
                : block.speaker
        }
        init(message: ReaderChat.Message) {
            id = message.block.id
            label = Copy.Provenance.chatRotorLabel(speaker: message.speaker, time: message.time)
        }
    }

    /// The chat rows a rotor names: each message that holds a cited span, and each turn's first message.
    private static func citedMessage(_ row: ReaderChat.Row) -> ReaderChat.Message? {
        guard case let .message(message) = row.kind, message.block.holdsFocus else { return nil }
        return message
    }

    private static func turnStart(_ row: ReaderChat.Row) -> ReaderChat.Message? {
        guard case let .message(message) = row.kind, message.block.startsTurn else { return nil }
        return message
    }

    /// Scroll to the cited turn after the first layout, show the wash, then say what was landed on (§4.4 Landing).
    /// The wash appears in one step: a `CitedPassage`'s marks are attributes of its selectable string, which no
    /// animation interpolates, so `spanReveal` here times only what can move with it.
    private func land(proxy: ScrollViewProxy, block: ReaderBlock.Key?, blocks: [ReaderBlock], chat: [ReaderChat.Row]?) {
        Task { @MainActor in
            await Task.yield()
            if let block {
                proxy.scrollTo(block, anchor: .center)
            } else if let chat, let newest = chat.last {
                // A chat opens at its newest message, history above (owner, 2026-10-19). A lazy stack places what it
                // has not measured by estimate, so it is asked twice: the second lands on the measured rows.
                proxy.scrollTo(newest.scrollID, anchor: .bottom)
                await Task.yield()
                proxy.scrollTo(newest.scrollID, anchor: .bottom)
            }
            switch ReaderLandingMotion.choose(isJump: jump != nil, trigger: jump ?? .pointer, isChat: chat != nil,
                                              landed: block != nil) {
            case .instant:
                Instant.run { state.washVisible = true }
            case .reveal:
                withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { state.washVisible = true }
            case .revealAndEmphasise:
                withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { state.washVisible = true }
                state.emphasise(reduceMotion: reduceMotion)
            }
            // The first block's piece of the words: a chunk holds at least
            // `chunkLimit / 2` scalars, so the 120 announced almost always sit
            // in one block, and never read a marker line out loud.
            guard presentation.focus != nil, let hit = blocks.first(where: { $0.holdsFocus }),
                  let wash = hit.washes.first(where: { $0.style != .other }) else { return }
            let words = ScalarText(hit.text).slice(wash.range.lowerBound, wash.range.upperBound)
            AccessibilityNotification.Announcement(Copy.Provenance.citedPassage(String(words.prefix(120))))
                .post()
        }
    }
}

/// What a `SourceSpansView` keeps between draws, held by its host: its keys arrive at the host's focus, and the host
/// resets it when it opens another source.
@Observable
@MainActor
final class SourceSpansState {
    /// A keyboard scroll: the row, the edge it lines up with, and a token so asking for the same row twice still moves.
    struct KeyScroll: Equatable {
        let id: AnyHashable
        let alignsTop: Bool
        let token: Int
    }

    /// Everything a draw needs from a document, computed once by one function.
    struct Layout {
        let blocks: [ReaderBlock]
        /// The chat rows, or nil for a document (`ReaderChat.isChat`).
        let chat: [ReaderChat.Row]?
        let landingBlock: ReaderBlock.Key?
        /// A note's formatted rows (`blocks` then holds the same lines); nil draws `blocks` or `chat`.
        var noteRows: [NotePageRow]? = nil
    }

    var washVisible = false
    var landingToken = 0
    /// The chat layout's unfolded long messages, by turn (owner, 2026-10-19); emptied on every load.
    var unfolded: Set<Int> = []
    /// The chat row at the top of the column, as the scroll view reports it (`scrollPosition(id:)`) — the keys move
    /// from here, so a trackpad scroll moves their starting point too — and the scroll a key asked for.
    var topRow: AnyHashable?
    var keyScroll: KeyScroll?
    var citedEmphasis: Double = 0

    @ObservationIgnored private var emphasisFade: Task<Void, Never>?
    /// The last layout built, so a key press or a hover redraw does not rebuild a 500-turn chat.
    @ObservationIgnored private var memoKey: MemoKey?
    @ObservationIgnored private var memo: Layout?

    private struct MemoKey: Hashable {
        let episode: String
        let hash: String
        let length: Int
        let unfolded: Set<Int>
        let presentation: ReaderPresentation
        let others: [Range<Int>]
        let note: UUID?
    }

    /// Another source is opening: forget where this one stood.
    func reset() {
        washVisible = false
        emphasisFade?.cancel()
        citedEmphasis = 0
        unfolded = []
        topRow = nil
        memoKey = nil
        memo = nil
    }

    func landAgain() { landingToken &+= 1 }

    /// An in-place jump is about to re-land: a pointer's hides the wash while the column moves; a keyboard's keeps it
    /// where it is, nothing fades out and back in (DR-60).
    func prepareJump(_ trigger: LooksZoom.Trigger) {
        emphasisFade?.cancel()
        Instant.run {
            citedEmphasis = 0
            if trigger == .pointer { washVisible = false }
        }
    }

    func toggle(_ turn: Int) {
        if unfolded.contains(turn) { unfolded.remove(turn) } else { unfolded.insert(turn) }
    }

    func scroll(to id: AnyHashable, alignsTop: Bool) {
        keyScroll = KeyScroll(id: id, alignsTop: alignsTop, token: (keyScroll?.token ?? 0) &+ 1)
    }

    /// The brief ring on the message a pointer jump landed on: held, then faded (`rowHighlightHold` /
    /// `rowHighlightFade`, the landed Settings row's timing); under Reduce Motion held for both and removed in one
    /// frame (R-O7). Never after a keyboard jump (DR-60) and never on opening the Reader.
    func emphasise(reduceMotion: Bool) {
        Instant.run { citedEmphasis = 1 }
        emphasisFade = Task { @MainActor in
            try? await Task.sleep(for: .seconds(CicadaMotion.rowHighlightHold))
            if reduceMotion { try? await Task.sleep(for: .seconds(CicadaMotion.rowHighlightFadeDuration)) }
            guard !Task.isCancelled else { return }
            withAnimation(CicadaMotion.rowHighlightFade(reduceMotion: reduceMotion)) { citedEmphasis = 0 }
        }
    }

    func layout(_ doc: EpisodeText, scalars: ScalarText, presentation: ReaderPresentation,
                others: [Range<Int>], note: NoteDocument? = nil) -> Layout {
        let key = MemoKey(episode: doc.episode, hash: doc.hash, length: doc.length, unfolded: unfolded,
                          presentation: presentation, others: others, note: note?.id)
        if memoKey == key, let memo { return memo }
        // A span the formatted page cannot show keeps the plain page: a citation's words are never lost to formatting.
        if let note, !ReaderChat.isChat(doc), (others + [presentation.focus].compactMap { $0 }).allSatisfy(note.draws) {
            let rows = note.rows(doc: doc, turn: doc.turns.first?.index ?? 0, focus: presentation.focus,
                                 focusStyle: presentation.focusStyle, others: others)
            let blocks = rows.map(\.reader)
            let landing = presentation.landing.flatMap { ReaderLayout.blockID(containing: $0, in: blocks) }
            let built = Layout(blocks: blocks, chat: nil, landingBlock: landing, noteRows: rows)
            memoKey = key
            memo = built
            return built
        }
        let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: presentation.focus,
                                         focusStyle: presentation.focusStyle,
                                         others: others.filter { $0 != presentation.focus })
        let landingBlock = presentation.landing.flatMap { ReaderLayout.blockID(containing: $0, in: blocks) }
        var chat: [ReaderChat.Row]?
        if ReaderChat.isChat(doc) {
            // A turn holding the cited words, or the one landed on, never folds: the wash is always on screen.
            chat = ReaderChat.rows(blocks: blocks, doc: doc, expanded: unfolded,
                                   keepOpen: ReaderChat.keepOpen(blocks: blocks, landing: landingBlock))
        }
        let built = Layout(blocks: blocks, chat: chat, landingBlock: landingBlock)
        memoKey = key
        memo = built
        return built
    }

    /// DR-68 — in a chat: ↑ / ↓ a message, the page keys five, ⌘↑ / Home to the start, ⌘↓ / End to the newest. Reads the
    /// layout last drawn, so a key press builds nothing.
    func key(_ press: KeyPress) -> KeyPress.Result {
        // ⌥↑ / ⌥↓ belong to the host's navigator; anything else with a modifier but ⌘ is not ours.
        guard !press.modifiers.contains(.option), !press.modifiers.contains(.control),
              let chat = memo?.chat, !chat.isEmpty else { return .ignored }
        let command = press.modifiers.contains(.command)
        let move: ReaderChatKeys.Move
        switch press.key {
        case .upArrow: move = command ? .first : .previous
        case .downArrow: move = command ? .last : .next
        case .pageUp: move = .pageUp
        case .pageDown: move = .pageDown
        case .home: move = .first
        case .end: move = .last
        default: return .ignored
        }
        let top = topRow.flatMap { id in chat.firstIndex { $0.scrollID == id } }
        guard let to = ReaderChatKeys.target(move, top: top, count: chat.count) else { return .ignored }
        scroll(to: chat[to.index].scrollID, alignsTop: to.alignsTop)
        return .handled
    }
}

extension ReaderPresentation {
    /// A source drawn for its spans rather than for one citation (ROR-15's use): nothing landed on unless asked, and no
    /// banner, because a span the server could not place simply has no `at`. The spans a host washes are its `others`.
    static func spans(landingOn span: SourceSpan? = nil, truncated: Bool = false) -> ReaderPresentation {
        let range = span?.range
        return ReaderPresentation(focus: range, focusStyle: span?.status == .derived ? .mention : .focus,
                                  banners: truncated ? [.truncated] : [], landing: range?.lowerBound)
    }
}
