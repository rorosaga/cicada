import SwiftUI

/// Owner 2026-11-23 — "why are there episodes and not a single string of the new un-consolidated conversation?". A
/// chat is stored a sitting at a time (messages more than three hours apart start a new file, so Sleep reads a bounded
/// piece and a quote's offsets stay put), and the Sleep page's chat card opened to those files. That is storage, not
/// the conversation: the card now opens what waits of the chat as ONE thread, oldest at the top and newest at the
/// bottom, the day said once where it changes — and above it, faded, the last few messages Sleep already read, then a
/// dotted line: where consolidation starts in a conversation that continues. It opens at the newest message, as every
/// chat does (owner 2026-11-25; the dotted line is met by scrolling up), and the jump button shows when the view sits
/// above it. Pure and tested (`ChatThreadTests`); `ChatThreadColumn` draws it.
enum ChatThread {
    /// How many sittings one read shows; "Earlier messages" (DR-40) shows the same number again. A chat's waiting
    /// sittings come whole up to `waitingPage`, so the dotted line is drawn with everything that waits under it.
    static let page = 12
    static let waitingPage = 30
    /// How many already-read messages stand, faded, above the line.
    static let contextMessages = 3

    /// Where a chat's card opens: its waiting sittings as one thread, with the sitting read just before them for the
    /// snippet above the line. A chat with nothing waiting opens every sitting the list holds — or, when that is one,
    /// the Reader's own document, which keeps what Sleep noted from it.
    static func target(_ group: ChatGroup, title: String) -> ReaderTarget? {
        let waiting = group.waiting
        let read = waiting.isEmpty ? group.sittings : waiting
        guard let newest = read.first else { return nil }
        if waiting.isEmpty, read.count == 1 { return EpisodeRowAction.reader(newest) }
        var before: String?
        if let oldest = waiting.last, let at = group.sittings.firstIndex(where: { $0.id == oldest.id }) {
            before = group.sittings[(at + 1)...].first(where: \.processed)?.id
        }
        return ReaderTarget(episode: newest.id, knownTitle: title,
                            thread: .init(chat: group.id, sittings: read.reversed().map(\.id),
                                          messages: group.messages, group: group.group,
                                          waiting: !waiting.isEmpty, before: before))
    }

    static func pageSize(_ thread: ReaderTarget.Thread) -> Int { thread.waiting ? waitingPage : page }

    /// The sittings on screen after `pages` reads: the newest `pages × size`, oldest first.
    static func shown(_ sittings: [String], pages: Int, size: Int = page) -> [String] {
        Array(sittings.suffix(max(1, pages) * size))
    }

    static func hasEarlier(_ sittings: [String], pages: Int, size: Int = page) -> Bool {
        sittings.count > max(1, pages) * size
    }

    /// The order the shown sittings are read in: newest first, so the end the person opens on fills first (a thread
    /// opens at its newest message, DESIGN_RULES 2026-10-19 (5) and 2026-11-25), then the sitting read just before the
    /// oldest, for the snippet, unless "Earlier messages" still holds older ones.
    static func loadOrder(shown: [String], before: String?, hasEarlier: Bool) -> [String] {
        var order = Array(shown.reversed())
        if !hasEarlier, let before { order.append(before) }
        return order
    }

    struct Section: Identifiable, Hashable {
        /// The sitting's episode id.
        let id: String
        let doc: EpisodeText
        let rows: [ReaderChat.Row]
    }

    struct Layout: Hashable {
        /// The last few messages Sleep already read, for the faded snippet above the line; empty when there are none.
        var context: [ReaderChat.Row] = []
        var contextDoc: EpisodeText?
        var sections: [Section] = []
    }

    /// The last `messages` messages of `rows`, as a snippet: nothing to unfold, no line of its own.
    static func tail(_ rows: [ReaderChat.Row], messages: Int) -> [ReaderChat.Row] {
        var left = messages
        var start = rows.endIndex
        for (n, row) in rows.enumerated().reversed() {
            guard case let .message(message) = row.kind, message.piece == .whole || message.piece == .first else {
                continue
            }
            start = n
            left -= 1
            if left == 0 { break }
        }
        var out = rows[start...].filter {
            switch $0.kind {
            case .toggle, .boundary: false
            default: true
            }
        }
        if let first = out.first { out[0] = ReaderChat.Row(id: first.id, kind: first.kind, gap: .none) }
        return out
    }

    /// `docs` (oldest first) as one conversation: each sitting's rows by the Reader's chat grammar, a day separator
    /// kept only where the day changes from the sitting before. The oldest sitting, when it grew after Sleep read it,
    /// starts at its first new message, and what came before it is the snippet; otherwise the snippet is the end of
    /// `before`, the sitting read just before. No snippet while earlier sittings are still to show (`complete`).
    static func layout(_ docs: [EpisodeText], before: EpisodeText? = nil, complete: Bool = true,
                       expanded: [String: Set<Int>] = [:], now: Date = Date(),
                       locale: Locale = .autoupdatingCurrent,
                       timeZone: TimeZone = .autoupdatingCurrent) -> Layout {
        var day: String?
        var out = Layout()
        for (n, doc) in docs.enumerated() {
            let scalars = ScalarText(doc.text)
            let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: nil, focusStyle: .focus,
                                             locale: locale, timeZone: timeZone)
            let newFrom = ReaderChanges.firstTurn(ReaderChanges.ranges(doc, scalars: scalars), blocks: blocks)
            var rows = ReaderChat.rows(blocks: blocks, doc: doc, expanded: expanded[doc.episode] ?? [],
                                       newFrom: newFrom, now: now, locale: locale, timeZone: timeZone)
            if let cut = rows.firstIndex(where: { $0.id == .boundary }) {
                // What came before is already consolidated: this thread is what waits.
                let read = Array(rows[..<cut])
                if n == 0, complete {
                    out.context = tail(read, messages: contextMessages)
                    out.contextDoc = doc
                }
                rows = Array(rows[(cut + 1)...])
                if let first = rows.first {
                    if case .day = first.kind {} else if let label = read.reversed().lazy.compactMap({ row -> String? in
                        if case let .day(label) = row.kind { label } else { nil }
                    }).first {
                        // The day the new messages are on, said where they start.
                        rows.insert(ReaderChat.Row(id: .day(-1), kind: .day(label), gap: .none), at: 0)
                    }
                }
            }
            if let first = rows.first, case let .day(label) = first.kind {
                if label == day {
                    rows.removeFirst()
                } else {
                    rows[0] = ReaderChat.Row(id: first.id, kind: first.kind, gap: out.sections.isEmpty ? .none : .section)
                }
            }
            if let first = rows.first, first.gap == .none, !out.sections.isEmpty {
                // A sitting with no day of its own still starts apart from the one before.
                rows[0] = ReaderChat.Row(id: first.id, kind: first.kind, gap: .newRun)
            }
            for row in rows { if case let .day(label) = row.kind { day = label } }
            if !rows.isEmpty { out.sections.append(Section(id: doc.episode, doc: doc, rows: rows)) }
        }
        if out.context.isEmpty, complete, let before, !out.sections.isEmpty {
            let scalars = ScalarText(before.text)
            let blocks = ReaderLayout.blocks(doc: before, scalars: scalars, focus: nil, focusStyle: .focus,
                                             locale: locale, timeZone: timeZone)
            out.context = tail(ReaderChat.rows(blocks: blocks, doc: before, now: now, locale: locale,
                                               timeZone: timeZone), messages: contextMessages)
            out.contextDoc = before
        }
        return out
    }
}

/// A thread's rows, flattened into the column's lazy stack: the faded snippet of what Sleep already read, the dotted
/// line, then every sitting as one conversation.
struct ChatThreadRows: View {
    let layout: ChatThread.Layout
    var onToggle: (Int, String) -> Void = { _, _ in }

    /// The snippet's bubbles and faces step back with its words.
    static let readOpacity: Double = 0.7

    var body: some View {
        if !layout.context.isEmpty, let doc = layout.contextDoc {
            // What Sleep already read, just enough to say where the new part starts: faded, and fading out upwards
            // (owner 2026-11-23).
            VStack(alignment: .leading, spacing: 0) {
                ReaderChatRows(rows: layout.context, landingTurn: nil, revealed: true,
                               messagesChat: ReaderChat.messagesChat(doc))
            }
            .environment(\.readTextFaded, true)
            .opacity(Self.readOpacity)
            .mask(LinearGradient(colors: [.black.opacity(0.15), .black], startPoint: .top, endPoint: .bottom))
            .accessibilityElement(children: .contain)
            .accessibilityLabel(Copy.Chat.alreadyRead)
            ReaderBoundaryLine(words: Copy.Provenance.newSinceRead)
                .padding(.vertical, CicadaTheme.scaled(20))
        }
        ForEach(layout.sections) { section in
            // A sitting's rows keep their own ids (a turn's index), so each sitting is its own stack.
            VStack(alignment: .leading, spacing: 0) {
                ReaderChatRows(rows: section.rows, landingTurn: nil, revealed: true,
                               messagesChat: ReaderChat.messagesChat(section.doc),
                               onToggle: { turn in onToggle(turn, section.id) })
            }
        }
    }
}

/// The Reader column for a chat thread (`ReaderTarget.thread`): the chat's face and name, how many messages wait, then
/// the conversation — every sitting from `GET /episodes/{id}/text`, drawn by the Reader's own chat rows (DESIGN_RULES
/// §9, 2026-10-19), with "Earlier messages" (DR-40) above when a long wait holds more than one read of sittings. Nothing here is a Store domain: the documents come from the Reader's own cache.
struct ChatThreadColumn: View {
    let thread: ReaderTarget.Thread
    let title: String

    @Environment(ProvenanceRouter.self) private var router
    @Environment(ProvenanceCache.self) private var cache
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @State private var docs: [String: EpisodeText] = [:]
    @State private var failed: Set<String> = []
    @State private var expanded: [String: Set<Int>] = [:]
    @State private var pages = 1
    /// Scrolled up from the newest message (`JumpToLatest`).
    @State private var latestY: CGFloat?
    @State private var awayFromLatest = false
    @State private var scroller = JumpToLatestScroller()

    private var size: Int { ChatThread.pageSize(thread) }
    private var shown: [String] { ChatThread.shown(thread.sittings, pages: pages, size: size) }
    private var hasEarlier: Bool { ChatThread.hasEarlier(thread.sittings, pages: pages, size: size) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            conversation
        }
        .task(id: thread) {
            pages = 1
            docs = [:]
            failed = []
            expanded = [:]
            latestY = nil
            awayFromLatest = false
            await loadShown()
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            if router.canGoBack {
                IconButton(systemName: "chevron.left", help: "\(Copy.Provenance.back) (⌥⌘[)",
                           accessibilityLabel: Copy.Provenance.back,
                           shortcut: KeyboardShortcut("[", modifiers: [.command, .option])) { router.back() }
            }
            MessageBubbleFace(name: title, photo: watcher?.cards[thread.chat]?.thumbnail, size: 28,
                              shared: watcher?.sharedPhotos[thread.chat])
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(CicadaTheme.displayFont(size: 20))
                    .tracking(CicadaTheme.displayTracking(size: 20))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                if thread.messages > 0 {
                    Text(Copy.Chat.waiting(thread.messages))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            IconButton(systemName: "xmark", help: Copy.Provenance.closeHelp,
                       accessibilityLabel: Copy.Provenance.close) { router.close() }
        }
        .padding(.top, CicadaTheme.scaled(18))
        .padding(.trailing, CicadaTheme.scaled(16))
        .padding(.bottom, CicadaTheme.scaled(12))
        .padding(.leading, CicadaTheme.scaled(ReaderColumn.inset))
    }

    @ViewBuilder
    private var conversation: some View {
        let held = shown.compactMap { docs[$0] }
        if held.isEmpty {
            InPlaceNote(text: failed.isEmpty ? Copy.ChatPage.loading : Copy.ChatPage.failed)
                .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
            Spacer(minLength: 0)
        } else {
            // The snippet waits for the oldest sitting, so the line never moves once drawn.
            let complete = !hasEarlier && shown.first.map { docs[$0] != nil } == true
            let layout = ChatThread.layout(held, before: thread.before.flatMap { docs[$0] }, complete: complete,
                                           expanded: expanded)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if hasEarlier {
                        TextButton(title: Copy.ChatPage.earlier) {
                            pages += 1
                            Task { await loadShown() }
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.bottom, CicadaTheme.spacingSM)
                    }
                    ChatThreadRows(layout: layout, onToggle: toggle)
                    if !failed.isDisjoint(with: shown) {
                        InPlaceNote(text: Copy.ChatPage.failed).padding(.top, CicadaTheme.spacingSM)
                    }
                    JumpToLatestAnchor(anchorY: $latestY, away: $awayFromLatest)
                }
                .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                .padding(.top, CicadaTheme.scaled(4))
                .padding(.bottom, CicadaTheme.spacingXL)
                .jumpToLatestSpace(scroller)
            }
            // DESIGN_RULES 2026-10-19 (5) and 2026-11-25: a chat opens at the newest message, history above — the
            // faded snippet and the dotted line included, which the person meets by scrolling up. Sittings that load
            // above, or "Earlier messages", keep the view where it is.
            .defaultScrollAnchor(.bottom)
            .jumpToLatest(anchorY: latestY, away: $awayFromLatest, scroller: scroller)
        }
    }

    /// "Show more" under a long message: a pointer or a key, one frame either way (DR-60).
    private func toggle(_ turn: Int, in sitting: String) {
        Instant.run {
            if expanded[sitting, default: []].contains(turn) {
                expanded[sitting]?.remove(turn)
            } else {
                expanded[sitting, default: []].insert(turn)
            }
        }
    }

    /// Reads the shown sittings not yet held, newest first, so the visible end fills first.
    private func loadShown() async {
        let target = thread
        let order = ChatThread.loadOrder(shown: shown, before: thread.before, hasEarlier: hasEarlier)
        for id in order where docs[id] == nil {
            let result = await cache.document(episode: id, focus: .none)
            guard !Task.isCancelled, target == thread else { return }
            if case let .loaded(doc) = result {
                docs[id] = doc
                failed.remove(id)
            } else if id != thread.before {
                failed.insert(id)
            }
        }
    }
}
