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
}

enum MessageBubbles {
    /// More than this many conversations: the rest are a "+N" bubble.
    static let maxShown = 3
    /// Each bubble overlaps the one before by this fraction of its size.
    static let overlap: CGFloat = 0.3

    struct Model: Equatable {
        var shown: [MessageBubble]
        var hidden: Int
        var messages: Int
        var label: String
        var accessibility: String
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
                                 help: Copy.Messages.bubbleHelp(name: shown, messages: item.messages))
        }
        let total = waiting.reduce(0) { $0 + $1.messages }
        return Model(shown: Array(bubbles.prefix(maxShown)), hidden: max(bubbles.count - maxShown, 0), messages: total,
                     label: Copy.Messages.waiting(total),
                     accessibility: bubbles.map(\.help).joined(separator: ", "))
    }
}

/// The stack itself: each conversation's Contacts photo, else a monogram (`EntityPictureFallback`, a person's ring);
/// nothing from the web. Hovering a bubble names it; clicking the stack (when `interactive`) lists the names.
struct MessageBubbleStack: View {
    var size: CGFloat = 20
    var interactive = true
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
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
                face(bubble, photo: watcher.cards[bubble.id]?.thumbnail, side: side)
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

    @ViewBuilder
    private func face(_ bubble: MessageBubble, photo: Data?, side: CGFloat) -> some View {
        Group {
            if let photo, let image = NSImage(data: photo) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                EntityPictureFallback(type: .person, name: bubble.name, units: size, frame: CGSize(width: side, height: side))
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
        // Depth is a ring, not a shadow: each bubble is cut from the one under it by the ground's own colour.
        .overlay(Circle().strokeBorder(CicadaTheme.bgBase, lineWidth: CicadaTheme.scaled(1.5)))
    }
}

/// One read-only row in the Sleep page's Details › What's waiting, beside the videos' row: the stacked bubbles,
/// "Messages" and the count. It starts nothing (the page's one cycle control is untouched) and is drawn only while a
/// ticked conversation has messages Sleep has not read.
struct MessagesWaitingRow: View {
    @Environment(MessagesWatcher.self) private var watcher: MessagesWatcher?
    @Environment(Store.self) private var store
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let watcher, !watcher.waiting.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Messages.sleepRowTitle)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    MessageBubbleStack()
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
