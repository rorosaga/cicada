import AppKit
import SwiftUI

/// G179 (owner, 2026-10-15: "Messages in consolidation can show as little profile-picture bubbles stacked … show
/// that one with its picture and the number of messages to consolidate") — the message conversations Sleep has not
/// read yet, as overlapping profile bubbles and one count. Pure here; drawn by `MessageBubbleStack`.
struct MessageBubble: Identifiable, Equatable {
    let id: String
    let name: String
    let initials: String
    let messages: Int
    let isAgent: Bool
    let help: String
    /// The correspondent's own page (`MessagesWaitingItem.page`), whose picture the bubble draws.
    var page: String? = nil
}

enum MessageBubbles {
    /// More than this many conversations: the rest are a "+N" bubble.
    static let maxShown = 3
    /// Each bubble overlaps the one before by this fraction of its size.
    static let overlap: CGFloat = 0.3
    /// The ground-coloured ring that cuts each bubble from the one under it, in units. It sits OUTSIDE the face: drawn
    /// over it (as it was), it covered a monogram's own 1.5 pt hue ring and left a near-black disc in dark appearance.
    static let groundRing: CGFloat = 1.5

    /// The face inside a bubble of `size` units: the bubble less its ground ring on both sides.
    static func faceUnits(_ size: CGFloat) -> CGFloat { size - 2 * groundRing }

    struct Model: Equatable {
        var shown: [MessageBubble]
        var hidden: Int
        var messages: Int
        var label: String
        var accessibility: String
    }

    /// The chat's page's resolved picture: the page the backend linked by the conversation's correspondent
    /// (`MessagesWaitingItem.page`), never a page found by name. Nil without a link or with no such page loaded.
    static func pagePicture(page: String?, nodes: [GraphNode]) -> EntityPictureRef? {
        guard let page, !page.isEmpty else { return nil }
        return nodes.first(where: { $0.id == page })?.pictureRef
    }

    /// What a bubble draws.
    enum Face: Equatable {
        case picture(PictureURL)
        case photo(Data)
        case monogram
    }

    /// The picture precedence for a chat (owner, 2026-10-16): the person's choice on the chat's page (their upload, or
    /// the monogram they chose) → the chat's Contacts photo (the card on this Mac, else the page's own Contacts rung) →
    /// the photo the chat shares in Messages → the monogram. A page's logo or public-profile rung is not a chat's face.
    static func face(page: EntityPictureRef?, contacts: Data?, shared: Data?) -> Face {
        if let page {
            switch page.source {
            case .upload: if let url = PictureURL.parse(page.url) { return .picture(url) }
            case .initials: return .monogram
            default: break
            }
        }
        if let contacts, !contacts.isEmpty { return .photo(contacts) }
        if let page, page.source == .contacts, let url = PictureURL.parse(page.url) { return .picture(url) }
        if let shared, !shared.isEmpty { return .photo(shared) }
        return .monogram
    }

    /// Most messages first; nil when nothing is waiting (the stack is not drawn then).
    static func model(_ items: [MessagesWaitingItem], name: (MessagesWaitingItem) -> String) -> Model? {
        let waiting = items.filter { $0.messages > 0 }.sorted {
            $0.messages != $1.messages ? $0.messages > $1.messages : $0.conversation < $1.conversation
        }
        guard !waiting.isEmpty else { return nil }
        let bubbles = waiting.map { item -> MessageBubble in
            let named = name(item).trimmingCharacters(in: .whitespacesAndNewlines)
            let shown = named.isEmpty ? item.name : named
            return MessageBubble(id: item.conversation, name: shown, initials: LogoImage.monogram(for: shown),
                                 messages: item.messages, isAgent: item.kind == "agent",
                                 help: Copy.Messages.bubbleHelp(name: shown, messages: item.messages), page: item.page)
        }
        let total = waiting.reduce(0) { $0 + $1.messages }
        return Model(shown: Array(bubbles.prefix(maxShown)), hidden: max(bubbles.count - maxShown, 0), messages: total,
                     label: Copy.Messages.waiting(total),
                     accessibility: bubbles.map(\.help).joined(separator: ", "))
    }
}

/// The stack itself: each conversation's face by `MessageBubbles.face` (its page's chosen picture, the Contacts photo,
/// the photo it shares in Messages, else a monogram); nothing from the web. Each face sits inside a ring of the ground's own colour, never over it,
/// so the monogram's hue ring stays whole. Hovering a bubble names it; clicking the stack (when `interactive`) lists the
/// names.
struct MessageBubbleStack: View {
    var size: CGFloat = 20
    var interactive = true
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @Environment(Store.self) private var store: Store?
    @State private var expanded = false

    var body: some View {
        if let watcher, let model = MessageBubbles.model(watcher.waiting, name: { watcher.name(ofWaiting: $0) }) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if interactive {
                    Button { expanded.toggle() } label: { stack(model, watcher: watcher) }
                        .buttonStyle(.plain)
                } else {
                    stack(model, watcher: watcher)
                }
                Text(model.label)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                if expanded {
                    Text(model.shown.map { "\($0.name) \($0.messages)" }.joined(separator: " · "))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(model.accessibility)
        }
    }

    private func stack(_ model: MessageBubbles.Model, watcher: MessagesWatcher) -> some View {
        let side = CicadaTheme.scaled(size)
        return HStack(spacing: -side * MessageBubbles.overlap) {
            ForEach(model.shown) { bubble in
                MessageBubbleFace(name: bubble.name, photo: watcher.cards[bubble.id]?.thumbnail, size: size,
                                  page: MessageBubbles.pagePicture(page: bubble.page, nodes: store?.graph.value?.nodes ?? []),
                                  shared: watcher.sharedPhotos[bubble.id])
                    .help(bubble.help)
            }
            if model.hidden > 0 {
                Text(Copy.Messages.more(model.hidden))
                    .font(CicadaTheme.font(size: size * 0.36, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: side, height: side)
                    .background(Circle().fill(CicadaTheme.bgOption))
                    .overlay(Circle().strokeBorder(CicadaTheme.bgBase, lineWidth: CicadaTheme.scaled(1.5)))
            }
        }
    }
}

/// One bubble: the face (`MessageBubbles.face`: the person's chosen picture, the Contacts photo, the photo the chat
/// shares in Messages, else the monogram) inset by
/// `MessageBubbles.groundRing` inside a disc of the ground's colour. Depth is a ring, not a shadow (DR-9): the disc is
/// what cuts this bubble from the one under it.
struct MessageBubbleFace: View {
    let name: String
    let photo: Data?
    var size: CGFloat = 20
    /// The chat's page's resolved picture (`MessageBubbles.pagePicture`), loaded from Cicada's own store.
    var page: EntityPictureRef? = nil
    /// The photo the chat shares in Messages (`MessagesWatcher.sharedPhotos`).
    var shared: Data? = nil

    @Environment(Store.self) private var store: Store?
    @State private var pageImage: NSImage?

    private var face: MessageBubbles.Face { MessageBubbles.face(page: page, contacts: photo, shared: shared) }

    var body: some View {
        let side = CicadaTheme.scaled(size)
        let inner = CicadaTheme.scaled(MessageBubbles.faceUnits(size))
        Group {
            if case .picture = face, let pageImage {
                Image(nsImage: pageImage).resizable().scaledToFill()
            } else if case .photo(let data) = face, let image = NSImage(data: data) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                EntityPictureFallback(type: .person, name: name, units: MessageBubbles.faceUnits(size),
                                      frame: CGSize(width: inner, height: inner), compactInitials: true)
            }
        }
        .frame(width: inner, height: inner)
        .clipShape(Circle())
        .frame(width: side, height: side)
        .background(Circle().fill(CicadaTheme.bgBase))
        .task(id: face) {
            guard case .picture(let url) = face, let bank = store?.bank else { pageImage = nil; return }
            pageImage = await PictureStore.shared.image(url, bank: bank)
        }
    }
}

/// The Waiting tab's Messages line when no Messages source row is there to carry the bubbles (the conversations'
/// messages are waiting but no episode is queued yet): the same grammar as a source row — the Messages mark, its name,
/// the stacked pictures and the count. With a source row present (`inline`), the bubbles ride that row instead
/// (`StudyListCard`) and this draws nothing, but still refreshes the waiting list when the queue moves. It starts
/// nothing (the page's one cycle control is untouched).
struct MessagesWaitingRow: View {
    var inline = false
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @Environment(Store.self) private var store
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !inline, let watcher, !watcher.waiting.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    // The source rows' chevron column, empty: this line has nothing to disclose.
                    Color.clear.frame(width: CicadaTheme.scaled(12))
                    OriginMark(origin: MessagesWatcher.channel, size: CicadaTheme.scaled(14))
                    Text(Copy.Messages.sleepRowTitle)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    MessageBubbleStack(size: 18)
                    Spacer(minLength: CicadaTheme.spacingSM)
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
                .background(hovering ? CicadaTheme.bgHover : Color.clear, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .onHover { hovering = $0 }
            }
        }
        // The waiting count moves when a capture lands or a read files; a refetch is one small GET.
        .task(id: store.status.value?.episodes.unprocessed) { await watcher?.refreshWaiting() }
    }
}
