import SwiftUI

/// Chat images (owner 2026-11-04) — one attachment of a chat-source turn, under its bubble, in the chat panel and the
/// Reader alike: the picture itself where the chat app holds it on this Mac (or, for Telegram, where the person's own
/// connection has it), a video with its play mark and length, a voice message or a file as a quiet row with its
/// length or size, and — when the file is not on this Mac — the same quiet row with its name and "Not on this Mac".
/// A click on anything that is here opens it in Quick Look (`ChatMediaPreview`). Ticked chats only: the tick is this
/// Mac's watcher's word for WhatsApp and Messages, the backend's for Telegram (`ChatMediaStore.shown`).
///
/// D's grammar (DESIGN_RULES §9, 2026-11-04): a picture sits on the bubble's side with the bubble's corners
/// (`CicadaTheme.shape`, DR-12) and the resting ring, never a shadow (DR-9, DR-10); a row tile wears the side's bubble
/// fill (DR-2); every word is meta text, every length a number with `monospacedDigit` (DR-21); the glyphs are SF
/// Symbols (DR-53); a pointer over a tile that opens dims it slightly — a tile is content, not a list row, so it takes
/// no row fill (DR-48, DR-63) — and nothing animates on the keyboard (DR-60).
struct ChatMediaTile: View {
    let file: ChatFile
    let side: ReaderChat.Side

    @Environment(WhatsAppWatcher.self) private var whatsApp: WhatsAppWatcher?
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @State private var shown: ChatMediaShown?
    @State private var hovering = false
    @State private var opening = false

    /// The longest side a picture is drawn at, before `uiScale`.
    static let pictureSide: CGFloat = 220
    static let radius: CGFloat = 12

    private var ticked: Bool {
        guard let source = file.source else { return false }
        switch source.channel {
        case .whatsApp: return whatsApp?.tickedIds.contains(source.chat) ?? false
        case .messages: return messages?.tickedIds.contains(source.chat) ?? false
        case .telegram: return true
        }
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: side == .person ? .trailing : .leading)
            .task(id: "\(file.source?.chat ?? "")|\(file.cacheKey)|\(ticked)") {
                shown = await ChatMediaStore.shared.shown(file, ticked: ticked)
            }
    }

    @ViewBuilder
    private var content: some View {
        let state = shown ?? .placeholder
        let lengthText = state.length.map(ChatMedia.length)
        let spoken = Copy.ChatFiles.spoken(kind: file.kind, name: file.name, length: lengthText,
                                           onMac: shown == nil || state.onMac)
        if let thumbnail = state.thumbnail {
            opener(state) { picture(thumbnail, length: lengthText) }
                .accessibilityLabel(spoken)
        } else {
            opener(state) { row(state, length: lengthText) }
                .accessibilityLabel(spoken)
        }
    }

    /// A click opens what is here in Quick Look; anything else is not a button at all.
    @ViewBuilder
    private func opener<Label: View>(_ state: ChatMediaShown, @ViewBuilder label: () -> Label) -> some View {
        if let large = state.large {
            Button { open(large) } label: { label() }
                .buttonStyle(.cicadaPlain)
                .onHover { hovering = $0 }
                .help(Copy.ChatFiles.openHelp)
                .accessibilityHint(Copy.ChatFiles.openHelp)
        } else {
            label().accessibilityElement(children: .ignore)
        }
    }

    private func picture(_ image: NSImage, length: String?) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.scaled(Self.radius))
        let size = Self.fitted(image.size, side: CicadaTheme.scaled(Self.pictureSide))
        return Image(nsImage: image)
            .resizable()
            .interpolation(.high)
            .scaledToFill()
            .frame(width: size.width, height: size.height)
            .clipShape(shape)
            .overlay { shape.strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1) }
            .overlay {
                if file.kind == "video" { playMark }
            }
            .overlay(alignment: .bottomLeading) {
                if let length { lengthBadge(length) }
            }
            .opacity(hovering ? 0.92 : 1)
    }

    private var playMark: some View {
        Image(systemName: "play.fill")
            .font(CicadaTheme.font(size: 15, weight: .semibold))
            .foregroundStyle(CicadaTheme.textPrimary)
            .frame(width: CicadaTheme.scaled(36), height: CicadaTheme.scaled(36))
            .background(Circle().fill(CicadaTheme.bgPane.opacity(0.88)))
            .accessibilityHidden(true)
    }

    private func lengthBadge(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.font(size: 11, weight: .medium))
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(6))
            .padding(.vertical, CicadaTheme.scaled(2))
            .background(Capsule().fill(CicadaTheme.bgPane.opacity(0.88)))
            .padding(CicadaTheme.scaled(6))
    }

    /// A voice message, a file, or anything not on this Mac: a quiet row in the side's bubble fill.
    private func row(_ state: ChatMediaShown, length: String?) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.scaled(Self.radius))
        let missing = shown != nil && !state.onMac
        let named = file.name != "unnamed" && !file.name.isEmpty
        let detail: String? = missing ? Copy.ChatFiles.notOnMac
            : length ?? file.size.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) }
        return HStack(spacing: CicadaTheme.scaled(10)) {
            Image(systemName: Self.symbol(file.kind))
                .font(CicadaTheme.font(size: 15, weight: .regular))
                .foregroundStyle(missing ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(20))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(named ? file.name : Copy.ChatFiles.kind(file.kind, name: file.name))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(missing ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                if let detail {
                    Text(detail)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(12))
        .padding(.vertical, CicadaTheme.scaled(8))
        .frame(maxWidth: CicadaTheme.scaled(Self.pictureSide + 40), alignment: .leading)
        .background(shape.fill(side == .person ? CicadaTheme.chatBubbleFill : CicadaTheme.chatBubbleOtherFill))
        .overlay { if side == .other { shape.strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1) } }
        .opacity(hovering ? 0.92 : 1)
    }

    static func symbol(_ kind: String) -> String {
        switch kind {
        case "image", "sticker": "photo"
        case "video": "play.rectangle"
        case "audio": "waveform"
        default: "doc"
        }
    }

    /// A picture's drawn size: its own aspect, its longest side at most `side`, never below a third of it.
    static func fitted(_ size: CGSize, side: CGFloat) -> CGSize {
        guard size.width > 0, size.height > 0 else { return CGSize(width: side, height: side) }
        let scale = side / max(size.width, size.height)
        return CGSize(width: max(side / 3, size.width * scale), height: max(side / 3, size.height * scale))
    }

    private func open(_ large: ChatMediaShown.Large) {
        guard !opening else { return }
        opening = true
        Task {
            defer { opening = false }
            if let url = await ChatMediaStore.shared.largeFile(file, large) {
                ChatMediaPreview.shared.show(url)
            }
        }
    }
}
