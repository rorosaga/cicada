import SwiftUI

// 2026-11-03 (owner, on a chat source's page: "this infinite scrollable list is shit UX") — every chat source's page
// (Messages, WhatsApp, Telegram) lists the chats Cicada holds under the page's one search, pinned chats first and then
// the apps' own order (most recent activity at the top, `channel_items._chat_rows`). A row is the chat's face (the page
// it stands for, else its own photo, else a monogram), its name, a dot with "Last synced …" (green, ticked) or "Not
// syncing" (grey) — the catalogue's own `StatusWord` — and its recency on the right as the apps say it. Right-click
// pins or unpins it (backend state, the chat's settings: every client of this bank lists it first). A click opens the
// chat's stored conversation in the panel at the right (`ChatConversationColumn`), drawn by the Reader's chat grammar
// (DESIGN_RULES §9, 2026-10-19) from the chat's episodes — never by reading the chat app again. Design notes and DR ids
// in DESIGN_RULES §9, 2026-11-03.

/// Which chat the Sources page's right-hand panel shows (in memory, the page's own; never a Store domain).
@Observable
@MainActor
final class ChatPanelRouter {
    struct Target: Equatable {
        let channel: String
        let item: ChannelItem
    }

    private(set) var target: Target?

    var isPresented: Bool { target != nil }

    func open(_ target: Target) { self.target = target }
    func close() { target = nil }
}

/// One chat on its source's page (DR-34's two-line row, DR-48 hover fill, DR-44 the Group pill, DR-52 the face).
struct ChatSourceRow: View {
    let item: ChannelItem
    let channel: String
    let now: Date

    @Environment(ChatPanelRouter.self) private var panel: ChatPanelRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(WhatsAppWatcher.self) private var whatsApp: WhatsAppWatcher?
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovering = false
    @State private var pinFailed = false

    private var check: Date? {
        switch channel {
        case WhatsAppWatcher.channel: whatsApp?.check?.at
        case MessagesWatcher.channel: messages?.check?.at
        default: nil
        }
    }

    private var selected: Bool { panel?.target?.item.id == item.id && panel?.target?.channel == channel }

    var body: some View {
        let pinned = item.pinned == true
        let sync = ChatSourcePage.syncLine(item, check: check, now: now)
        let recency = ChatSourcePage.recency(item, now: now)
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                face
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(item.title)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        if item.group == true { Tag(text: Copy.Chats.group) }
                    }
                    StatusWord(word: sync.text, tone: sync.synced ? .on : .off)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                VStack(alignment: .trailing, spacing: CicadaTheme.scaled(3)) {
                    if let recency {
                        Text(recency.text)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                            .fixedSize()
                            .help(recency.help)
                    }
                    if pinned {
                        Image(systemName: "pin.fill")
                            .font(CicadaTheme.font(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .help(Copy.ChatPage.pinned)
                            .accessibilityHidden(true)
                    }
                }
            }
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine),
                   maxHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .rowHoverFill(hovering: hovering || selected)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(pinFailed ? Copy.ChatPage.pinFailed : Copy.ChatPage.openHelp)
        .contextMenu {
            Button(pinned ? Copy.ChatPage.unpin : Copy.ChatPage.pin) { setPinned(!pinned) }
        }
        .accessibilityLabel(Copy.ChatPage.rowLabel(item.title, sync: sync.text, recency: recency?.help, pinned: pinned))
        .accessibilityHint(Copy.ChatPage.openHelp)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityAction(named: pinned ? Copy.ChatPage.unpin : Copy.ChatPage.pin) { setPinned(!pinned) }
    }

    @ViewBuilder
    private var face: some View {
        let side = CicadaTheme.scaled(28)
        if let chat = item.chat {
            ChatFace(chat: chat, side: side)
        } else {
            ChatFace(id: item.id, label: item.title, photo: nil, side: side)
        }
    }

    /// The panel opens from the right on the columns' curve (DR-61), and the Reader it replaces closes (DR-29).
    private func open() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance?.isPresented == true { provenance?.close() }
            panel?.open(.init(channel: channel, item: item))
        }
    }

    private func setPinned(_ on: Bool) {
        guard let source = ChatSourcePage.settingsSource[channel] else { return }
        Task {
            do {
                try await APIClient.shared.setChatPinned(source: source, id: item.id, pinned: on)
                pinFailed = false
            } catch {
                pinFailed = true
            }
            await cache?.refresh(channel)
        }
    }
}

/// The Sources page's right-hand panel for one chat: its face and name, then the stored conversation, newest at the
/// bottom, each sitting from `GET /episodes/{id}/text` drawn by the Reader's own chat rows (`ReaderChat`), with
/// "Earlier messages" (DR-40) above for the sittings before. An unticked chat shows its face, name and recency only.
struct ChatConversationColumn: View {
    let target: ChatPanelRouter.Target
    let onClose: () -> Void

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @State private var docs: [String: EpisodeText] = [:]
    @State private var failed: Set<String> = []
    @State private var pages = 1

    private var item: ChannelItem { target.item }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if item.ticked == true {
                conversation
            } else {
                InPlaceNote(text: Copy.ChatPage.notTicked)
                    .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgPane)
        .columnEdge()   // DR-9 — the column's leading edge is the one rule, as the Reader's
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { Instant.run { onClose() } }   // DR-60: a keyboard path never animates
        .task(id: item.id) {
            pages = 1
            docs = [:]
            failed = []
            guard item.ticked == true else { return }
            await cache?.refreshSittings(item.id)
            await loadShown()
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            if let chat = item.chat {
                ChatFace(chat: chat, side: CicadaTheme.scaled(28))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(CicadaTheme.displayFont(size: 20))
                    .tracking(CicadaTheme.displayTracking(size: 20))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                if let recency = ChatSourcePage.recency(item, now: .now) {
                    Text(recency.help)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            IconButton(systemName: "xmark", help: Copy.ChatPage.closeHelp, accessibilityLabel: Copy.ChatPage.close,
                       action: onClose)
        }
        .padding(.top, CicadaTheme.scaled(18))
        .padding(.trailing, CicadaTheme.scaled(16))
        .padding(.bottom, CicadaTheme.scaled(12))
        .padding(.leading, CicadaTheme.scaled(ReaderColumn.inset))
    }

    @ViewBuilder
    private var conversation: some View {
        if let page = cache?.sittings(item.id) {
            let shown = ChatSourcePage.shownSittings(page.sittings, pages: pages)
            if page.ticked == false {
                // The backend's word on the tick wins over the row's (a tick changed since the list was read).
                InPlaceNote(text: Copy.ChatPage.notTicked).padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                Spacer(minLength: 0)
            } else if shown.isEmpty {
                InPlaceNote(text: Copy.ChatPage.empty).padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                Spacer(minLength: 0)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if ChatSourcePage.hasEarlier(page.sittings, pages: pages) {
                            TextButton(title: Copy.ChatPage.earlier) {
                                pages += 1
                                Task { await loadShown() }
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.bottom, CicadaTheme.spacingSM)
                        }
                        ForEach(shown) { sitting in
                            sittingView(sitting)
                        }
                    }
                    .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                    .padding(.bottom, CicadaTheme.spacingXL)
                }
                // DESIGN_RULES 2026-10-19 (5): a chat opens at the newest message, history above.
                .defaultScrollAnchor(.bottom)
            }
        } else if cache?.sittingsFailed(item.id) == true {
            InPlaceNote(text: Copy.ChatPage.failed).padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
            Spacer(minLength: 0)
        } else {
            InPlaceNote(text: Copy.ChatPage.loading).padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func sittingView(_ sitting: ChatSitting) -> some View {
        if let doc = docs[sitting.id] {
            let scalars = ScalarText(doc.text)
            let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: nil, focusStyle: .focus)
            VStack(alignment: .leading, spacing: 0) {
                ReaderChatRows(rows: ReaderChat.rows(blocks: blocks, doc: doc), landingTurn: nil, revealed: true,
                               messagesChat: ReaderChat.messagesChat(doc))
            }
            .padding(.bottom, CicadaTheme.scaled(16))
        } else if failed.contains(sitting.id) {
            InPlaceNote(text: Copy.ChatPage.failed)
        } else {
            InPlaceNote(text: Copy.ChatPage.loading)
        }
    }

    /// Reads the shown sittings not yet held, newest first, so the bottom of the panel fills first.
    private func loadShown() async {
        guard let page = cache?.sittings(item.id) else { return }
        for sitting in ChatSourcePage.shownSittings(page.sittings, pages: pages).reversed()
        where docs[sitting.id] == nil {
            do {
                let answer = try await APIClient.shared.fetchEpisodeText(episode: sitting.id, focus: .none, etag: nil)
                if let doc = answer.value { docs[sitting.id] = doc }
            } catch {
                failed.insert(sitting.id)
            }
        }
    }
}
