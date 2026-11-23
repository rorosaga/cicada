import SwiftUI

/// Owner 2026-11-23 — "for conversations like those in instinct i get the episodes thing but shouldnt it be just one
/// chat with the green marker (bc new messages), and per chat the number of new messages in total?". A chat is stored
/// a sitting at a time (messages more than three hours apart start a new one), so a source's waiting list was a card
/// per sitting. Pure: a source's items, newest first, become one entry per chat — every waiting sitting of it under
/// one card, its messages counted once — with everything else left as it was (`ChatGroupsTests`).
struct ChatGroup: Identifiable, Equatable {
    let id: String
    /// The correspondent's or the group's name, nil when the chat has none on record.
    let name: String?
    let group: Bool
    let selfChat: Bool
    /// The chat's sittings in this list, newest first.
    let sittings: [EpisodeQueueItem]

    static func == (a: ChatGroup, b: ChatGroup) -> Bool {
        a.id == b.id && a.name == b.name && a.sittings.map(\.id) == b.sittings.map(\.id)
    }

    /// The sittings still to read; a read one stays listed (faded) but waits for nothing.
    var waiting: [EpisodeQueueItem] { sittings.filter { !$0.processed } }
    /// The messages waiting, over every waiting sitting.
    var messages: Int { waiting.reduce(0) { $0 + ($1.chat?.messages ?? 0) } }
    /// When the chat last moved: its newest sitting's last change.
    var latest: String? { sittings.first.map { $0.changedAt ?? $0.timestamp } }
}

enum QueueEntry: Identifiable {
    case chat(ChatGroup)
    case episode(EpisodeQueueItem)

    var id: String {
        switch self {
        case .chat(let group): "chat:\(group.id)"
        case .episode(let item): item.id
        }
    }
}

enum ChatGroups {
    /// `items` (newest first) as entries in the same order: a chat stands where its newest sitting stood.
    static func entries(_ items: [EpisodeQueueItem]) -> [QueueEntry] {
        var order: [QueueEntry] = []
        var sittings: [String: [EpisodeQueueItem]] = [:]
        var place: [String: Int] = [:]
        for item in items {
            guard let chat = item.chat else { order.append(.episode(item)); continue }
            if place[chat.id] == nil {
                place[chat.id] = order.count
                order.append(.episode(item))   // the chat's place; filled below
            }
            sittings[chat.id, default: []].append(item)
        }
        for (id, index) in place {
            let all = sittings[id] ?? []
            // The name as the newest sitting that has one recorded it.
            let named = all.compactMap(\.chat).first { ($0.name ?? "").isEmpty == false }
            let first = all[0].chat
            order[index] = .chat(ChatGroup(id: id, name: named?.name, group: first?.group ?? false,
                                           selfChat: first?.selfChat ?? false, sittings: all))
        }
        return order
    }

    /// The card's name: the chat's own, else what it is in words.
    static func title(_ group: ChatGroup) -> String {
        if let name = group.name, !name.isEmpty { return name }
        if group.selfChat { return Copy.Chat.notesToYourself }
        return group.group ? Copy.Chat.unnamedGroup : Copy.Chat.unnamed
    }

    /// The card's second line: how many messages wait, in how many sittings when more than one, and how long ago.
    static func meta(_ group: ChatGroup, now: Date = Date(), locale: Locale = .autoupdatingCurrent) -> [String] {
        var parts: [String] = []
        if group.messages > 0 { parts.append(Copy.chatMessages(group.messages, locale: locale)) }
        if group.waiting.count > 1 { parts.append(Copy.chatSittings(group.waiting.count, locale: locale)) }
        if let latest = group.latest, let date = parseEpisodeTimestamp(latest) {
            parts.append(Copy.OriginCard.ago(date, now: now))
        }
        if group.waiting.isEmpty { parts.append("read") }
        return parts
    }
}

/// One chat in a source card: its face wearing how many messages wait (the source mark's badge grammar), its name
/// behind the "new" dot — a chat with waiting messages is always new messages — and one line of how many, in how many
/// sittings, how long ago. A click opens its one sitting in the Reader; with several it opens in place to them, each
/// its own episode card (which keeps its own marker: a sitting that grew since Sleep read it is "updated", and the
/// Reader highlights the new messages).
struct ChatCard: View {
    let group: ChatGroup
    @State private var open = false
    @State private var hovering = false
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let face: CGFloat = 30

    /// The Contacts card's name when this Mac has one for the chat (Messages only), else the recorded name.
    private var title: String {
        if let card = watcher?.cards[group.id], !card.name.isEmpty { return card.name }
        return ChatGroups.title(group)
    }

    var body: some View {
        let waiting = !group.waiting.isEmpty
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Button(action: press) {
                HStack(alignment: .center, spacing: CicadaTheme.spacingLG) {
                    MessageBubbleFace(name: title, photo: watcher?.cards[group.id]?.thumbnail, size: Self.face,
                                      shared: watcher?.sharedPhotos[group.id])
                        .overlay(alignment: .topTrailing) {
                            StudyListCard.badge(group.messages > 0 ? group.messages : nil, knockout: CicadaTheme.bgOption)
                        }
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                        HStack(alignment: .center, spacing: CicadaTheme.scaled(7)) {
                            if waiting {
                                Circle().fill(EpisodeChange.new.color)
                                    .frame(width: CicadaTheme.scaled(Tag.dotSize + 1),
                                           height: CicadaTheme.scaled(Tag.dotSize + 1))
                                    .accessibilityHidden(true)
                            }
                            Text(title)
                                .font(CicadaTheme.rowFont)
                                .foregroundStyle(waiting ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                                .lineLimit(1)
                        }
                        Text(ChatGroups.meta(group).joined(separator: " · "))
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .originCardChrome(tone: waiting ? .plain : .past, hovering: hovering, held: open)
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .help(group.sittings.count > 1 ? Copy.Chat.sittingsHelp : Copy.SleepDetailsWords.openHint(nil))
            .accessibilityLabel(([title] + ChatGroups.meta(group) + (waiting ? [EpisodeChange.new.spoken] : []))
                .joined(separator: ", "))
            .accessibilityValue(group.sittings.count > 1 ? (open ? Copy.Lists.expanded : Copy.Lists.collapsed) : "")
            if open {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(group.sittings) { EpisodeCard(item: $0) }
                }
                .padding(.leading, CicadaTheme.spacingLG)
                .transition(.opacity)
            }
        }
    }

    /// One sitting opens in the Reader; several open in place.
    private func press() {
        if group.sittings.count == 1, let only = group.sittings.first, let reader {
            reader.open(EpisodeRowAction.reader(only))
        } else {
            withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { open.toggle() }
        }
    }
}
