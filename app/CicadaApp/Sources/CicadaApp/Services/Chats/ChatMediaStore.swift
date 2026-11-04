import AppKit
import Foundation
import ImageIO
import Quartz
import QuickLookThumbnailing

/// What a chat attachment's tile draws (2026-11-04): whether the file is on this Mac (else the quiet placeholder with
/// its name), a thumbnail when one can be made, a video's or voice message's length, and what a click opens large.
struct ChatMediaShown: @unchecked Sendable {
    enum Large: Hashable, Sendable {
        /// The chat app's own file on this Mac, opened in Quick Look where it is (never copied).
        case file(URL)
        /// A Telegram photo, asked of the person's own connection on the click (`/media/full`).
        case telegram
    }

    var onMac = false
    var thumbnail: NSImage? = nil
    var length: Double? = nil
    var large: Large? = nil

    static let placeholder = ChatMediaShown()
}

/// Resolves a ticked chat's attachments to what the chat app already holds (`ChatMedia`), at view time. Per chat, the
/// store's media list is read once and kept in memory for `indexLife`; each thumbnail is made once (Quick Look's
/// generator, ≤ `thumbnailSide` px) and kept in `ChatMediaCache`, outside every bank. A chat that is not ticked is
/// never read, and whatever was kept of it goes (`ChatMediaCache.forget`). Never a Store domain.
@MainActor
final class ChatMediaStore {
    static let shared = ChatMediaStore()

    typealias TelegramFetch = @Sendable (String, ChatFile, Bool) async throws -> Data?
    typealias Thumbnailer = @Sendable (URL) async -> (image: NSImage, jpeg: Data)?

    var whatsAppStore: URL
    var messagesDatabase: URL
    var cacheRoot: URL
    var telegram: TelegramFetch
    var thumbnailer: Thumbnailer
    /// How long a chat's media list is trusted before it is read again (a chat keeps receiving files).
    var indexLife: TimeInterval = 60
    nonisolated static let thumbnailSide: CGFloat = 480

    private var indexes: [ChatMediaSource: (read: Date, items: [ChatMediaCandidate])] = [:]
    private var reading: [ChatMediaSource: Task<[ChatMediaCandidate], Never>] = [:]
    private var shown: [String: ChatMediaShown] = [:]
    /// #597 review B2 — bumped by every `forget` (an untick). Whatever an ask learnt or made under an older generation
    /// is discarded when it lands: no thumbnail, no large photo, no media list and no tile outlives the untick that
    /// came while it was loading.
    private var generations: [ChatMediaSource: Int] = [:]

    private func generation(_ source: ChatMediaSource) -> Int { generations[source, default: 0] }

    init(whatsAppStore: URL = WhatsAppReader.standardStore, messagesDatabase: URL = MessagesReader.standardDatabase,
         cacheRoot: URL = ChatMediaCache.root,
         telegram: @escaping TelegramFetch = { try await APIClient.shared.telegramChatMedia(chat: $0, file: $1, full: $2) },
         thumbnailer: @escaping Thumbnailer = { await ChatMediaStore.thumbnail(of: $0) }) {
        self.whatsAppStore = whatsAppStore
        self.messagesDatabase = messagesDatabase
        self.cacheRoot = cacheRoot
        self.telegram = telegram
        self.thumbnailer = thumbnailer
    }

    private func memoKey(_ source: ChatMediaSource, _ file: ChatFile) -> String {
        "\(source.channel.rawValue)|\(source.chat)|\(file.cacheKey)"
    }

    /// A chat was unticked: its media list, its tiles and its thumbnails go.
    func forget(_ source: ChatMediaSource) {
        generations[source, default: 0] += 1
        indexes[source] = nil
        reading[source]?.cancel()
        reading[source] = nil
        let prefix = "\(source.channel.rawValue)|\(source.chat)|"
        shown = shown.filter { !$0.key.hasPrefix(prefix) }
        ChatMediaCache.forget(source, root: cacheRoot)
    }

    /// What one attachment's tile draws. `ticked` is the chat's tick as this Mac knows it (the watcher's); Telegram's
    /// is the backend's to check.
    func shown(_ file: ChatFile, ticked: Bool) async -> ChatMediaShown {
        guard let source = file.source else { return .placeholder }
        guard ticked || source.channel == .telegram else {
            forget(source)
            return .placeholder
        }
        let key = memoKey(source, file)
        if let hit = shown[key] { return hit }
        let started = generation(source)
        let answer: ChatMediaShown
        switch source.channel {
        case .telegram: answer = await telegramShown(source, file)
        case .whatsApp, .messages: answer = await localShown(source, file, generation: started)
        }
        guard generation(source) == started else { return .placeholder }   // unticked while it loaded
        shown[key] = answer
        return answer
    }

    // MARK: WhatsApp and Messages: the chat app's own files on this Mac

    private func index(_ source: ChatMediaSource) async -> [ChatMediaCandidate] {
        if let held = indexes[source], Date().timeIntervalSince(held.read) < indexLife { return held.items }
        if let running = reading[source] { return await running.value }
        let store = whatsAppStore, database = messagesDatabase
        let started = generation(source)
        let task = Task.detached(priority: .userInitiated) { () -> [ChatMediaCandidate] in
            switch source.channel {
            case .whatsApp:
                let reader = WhatsAppReader(store: store)
                guard let chat = try? reader.chats(ids: [source.chat]).first else { return [] }
                return (try? reader.media(chat)) ?? []
            case .messages:
                return (try? MessagesReader(database: database).media(conversation: source.chat)) ?? []
            case .telegram:
                return []
            }
        }
        reading[source] = task
        let items = await task.value
        guard generation(source) == started else { return [] }   // unticked while it read: nothing is kept
        reading[source] = nil
        indexes[source] = (Date(), items)
        return items
    }

    private func localShown(_ source: ChatMediaSource, _ file: ChatFile, generation started: Int) async -> ChatMediaShown {
        guard let hit = ChatMedia.pick(await index(source), file: file) else { return .placeholder }
        var out = ChatMediaShown(onMac: hit.file != nil, length: hit.length)
        if let local = hit.file { out.large = .file(local) }
        if let kept = ChatMediaCache.read(source, key: file.cacheKey, root: cacheRoot), let image = NSImage(data: kept) {
            out.thumbnail = image
        } else if file.isVisual, let from = hit.file ?? hit.thumbnail, let made = await thumbnailer(from) {
            guard generation(source) == started else { return .placeholder }   // unticked meanwhile: nothing written
            out.thumbnail = made.image
            ChatMediaCache.write(made.jpeg, source, key: file.cacheKey, root: cacheRoot)
        }
        if out.length == nil, file.isTimed, let local = hit.file {
            out.length = await ChatMediaDuration.seconds(local)
        }
        return out
    }

    /// A file's thumbnail, at most `thumbnailSide` px, as an image and the JPEG kept for it: a picture through
    /// ImageIO's own thumbnailer (JPEG, PNG, HEIC, GIF, WebP — orientation applied), anything else (a video's frame)
    /// through Quick Look's generator. Nil for a file neither can draw.
    nonisolated static func thumbnail(of url: URL) async -> (image: NSImage, jpeg: Data)? {
        var made = imageThumbnail(url)
        if made == nil { made = await quickLookThumbnail(url) }
        if let cg = made {
            let rep = NSBitmapImageRep(cgImage: cg)
            guard let jpeg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.82]) else { return nil }
            return (NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height)), jpeg)
        }
        return nil
    }

    nonisolated static func imageThumbnail(_ url: URL) -> CGImage? {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil), CGImageSourceGetCount(source) > 0 else {
            return nil
        }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                        kCGImageSourceCreateThumbnailWithTransform: true,
                                        kCGImageSourceThumbnailMaxPixelSize: Int(thumbnailSide)]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    nonisolated static func quickLookThumbnail(_ url: URL) async -> CGImage? {
        let request = QLThumbnailGenerator.Request(fileAt: url, size: CGSize(width: thumbnailSide, height: thumbnailSide),
                                                   scale: 1, representationTypes: .thumbnail)
        return try? await QLThumbnailGenerator.shared.generateBestRepresentation(for: request).cgImage
    }

    // MARK: Telegram: asked of the person's own connection, by the backend

    private struct TelegramAnswer: Decodable {
        var found = false
        var kind: String?
        var length: Double?
        var preview: String?

        /// The wire's word for a video's or voice message's length (`TelegramMediaResponse`).
        enum CodingKeys: String, CodingKey { case found, kind, length = "duration", preview }
    }

    private func telegramShown(_ source: ChatMediaSource, _ file: ChatFile) async -> ChatMediaShown {
        guard let data = try? await telegram(source.chat, file, false),
              let answer = try? JSONDecoder().decode(TelegramAnswer.self, from: data), answer.found else {
            return .placeholder
        }
        var out = ChatMediaShown(onMac: true, length: answer.length)
        if let preview = answer.preview.flatMap({ Data(base64Encoded: $0) }), let image = NSImage(data: preview) {
            out.thumbnail = image
        }
        if file.kind == "image" || file.kind == "sticker" { out.large = .telegram }
        return out
    }

    /// The file a click opens in Quick Look: the chat app's own, or a Telegram photo asked now and kept beside the
    /// thumbnails (outside every bank, gone on untick). Nil when there is none.
    func largeFile(_ file: ChatFile, _ large: ChatMediaShown.Large) async -> URL? {
        switch large {
        case let .file(url):
            return url
        case .telegram:
            guard let source = file.source else { return nil }
            let key = file.cacheKey + "-full"
            if let kept = ChatMediaCache.file(source, key: key, root: cacheRoot),
               FileManager.default.fileExists(atPath: kept.path) { return kept }
            let started = generation(source)
            guard let data = try? await telegram(source.chat, file, true), !data.isEmpty,
                  generation(source) == started else { return nil }   // unticked while it loaded: nothing written
            return ChatMediaCache.write(data, source, key: key, root: cacheRoot)
        }
    }
}

/// Quick Look for a chat attachment (2026-11-04): the system's own preview panel, opened on one file. The app
/// delegate answers the panel's controller questions (`CicadaAppDelegate`'s extension below), so the panel stays the
/// app's for as long as it is open.
@MainActor
final class ChatMediaPreview: NSObject, QLPreviewPanelDataSource {
    static let shared = ChatMediaPreview()
    private(set) var url: URL?

    func show(_ url: URL) {
        self.url = url
        guard let panel = QLPreviewPanel.shared() else { return }
        if panel.isVisible {
            panel.reloadData()
        } else {
            panel.makeKeyAndOrderFront(nil)
        }
    }

    nonisolated func numberOfPreviewItems(in panel: QLPreviewPanel!) -> Int {
        MainActor.assumeIsolated { url == nil ? 0 : 1 }
    }

    nonisolated func previewPanel(_ panel: QLPreviewPanel!, previewItemAt index: Int) -> (any QLPreviewItem)! {
        MainActor.assumeIsolated { url.map { $0 as NSURL } }
    }
}

/// The preview panel looks up the responder chain for its controller; the app delegate is in it whatever window is key,
/// so the chat panel's Quick Look needs no view of its own in the chain.
extension CicadaAppDelegate {
    override func acceptsPreviewPanelControl(_ panel: QLPreviewPanel!) -> Bool { ChatMediaPreview.shared.url != nil }

    override func beginPreviewPanelControl(_ panel: QLPreviewPanel!) { panel.dataSource = ChatMediaPreview.shared }

    override func endPreviewPanelControl(_ panel: QLPreviewPanel!) { panel.dataSource = nil }
}
