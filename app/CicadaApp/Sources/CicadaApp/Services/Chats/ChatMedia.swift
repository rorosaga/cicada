import CryptoKit
import Foundation

// Chat images (owner 2026-11-04: "we're syncing WhatsApp, for example my own chat with myself, but I don't see images
// appearing when I open the chat inside the app. I think images throughout chat applications and everything should
// appear, if possible.") — pure and tested (`ChatMediaTests`).
//
// **The rails.** The bank keeps an attachment's kind, name and size, never a path and never a byte (`turn_extras`).
// At view time, and only for a chat the person ticked, the APP finds the file the chat app already holds on this Mac —
// WhatsApp's media folder in its group container, Messages' `Attachments` — by the turn's own second and the
// attachment's stored name and place (`pick`), and draws a thumbnail it makes here, kept outside every bank under
// `$CICADA_HOME/chat-media/<source>/<chat>/` until the chat is unticked (`ChatMediaCache`). Telegram's are asked of
// the person's own Telegram connection by the backend, the same way (`GET /sources/telegram/chats/{id}/media`). Nothing
// is copied into a bank, posted anywhere, or read by Sleep. A file not on this Mac is a quiet placeholder with its name.

/// The chat a sitting belongs to, for its pictures: the source (`imessage`, `whatsapp`, `telegram-chats`, each the
/// episodes' origin) and the chat's id (each reader's hash, as the bank keeps it).
struct ChatMediaSource: Hashable, Sendable {
    enum Channel: String, Sendable, CaseIterable {
        case messages = "imessage"
        case whatsApp = "whatsapp"
        case telegram = "telegram-chats"
    }

    let channel: Channel
    let chat: String
}

/// One attachment of a turn, as a tile asks for it: what the bank says (kind, name, size), the turn's time as stored,
/// and its place among the sitting's attachments of the same second, kind and name (`n`).
struct ChatFile: Hashable, Sendable {
    let source: ChatMediaSource?
    let kind: String
    let name: String
    let size: Int?
    /// The turn's `ts` exactly as the backend wrote it (Telegram's ask carries it back), and as an instant.
    let at: String?
    let n: Int

    var instant: Date? { at.flatMap(ChatMedia.instant) }
    var isVisual: Bool { kind == "image" || kind == "sticker" || kind == "video" }
    var isTimed: Bool { kind == "video" || kind == "audio" }

    /// The thumbnail cache's key: the turn's time, the attachment and its place — never a path.
    var cacheKey: String {
        let raw = [at ?? "", kind, name, String(n)].joined(separator: "\u{1f}")
        return SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24).description
    }
}

/// One file a chat app holds for a chat, as its store lists it: the message's order and time, the attachment's name
/// and kind exactly as the backend stored them (`normalizedName`, `kind`), and where the file and its own thumbnail
/// are (resolved inside the app's folder only, `ChatMediaLocal`). App-side only, never posted.
struct ChatMediaCandidate: Hashable, Sendable {
    let order: Int64
    let date: Date
    let name: String
    let kind: String
    var file: URL? = nil
    var thumbnail: URL? = nil
    var length: Double? = nil
}

enum ChatMedia {
    /// A turn's time is its message's, to the second (`messages_source.apple_time`, `chat_live.utc_from_unix`).
    static let window: TimeInterval = 1.5
    /// The backend's cap on a name (`messages_source.ATTACHMENT_NAME_CAP`).
    static let nameCap = 120

    static func instant(_ raw: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: raw) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: raw)
    }

    /// The chat a sitting belongs to, from its origin and its source id (`<origin>:<chat>:…`); nil for anything that
    /// is not a sitting of a chat source.
    static func source(_ doc: EpisodeText) -> ChatMediaSource? {
        guard let origin = doc.origin, let channel = ChatMediaSource.Channel(rawValue: origin),
              let id = doc.conversationId, id.hasPrefix(origin + ":") else { return nil }
        let chat = id.dropFirst(origin.count + 1).prefix { $0 != ":" }
        guard (16...64).contains(chat.count), chat.allSatisfy(\.isHexDigit) else { return nil }
        return ChatMediaSource(channel: channel, chat: String(chat))
    }

    /// Every turn's attachments as tiles ask for them, keyed by turn index: each with its place among the sitting's
    /// attachments of the same second, kind and name — the order the stores list them in (`pick`).
    static func files(_ doc: EpisodeText) -> [Int: [ChatFile]] {
        let source = source(doc)
        var seen: [String: Int] = [:]
        var out: [Int: [ChatFile]] = [:]
        for turn in doc.turns.sorted(by: { $0.index < $1.index }) {
            guard let attachments = turn.extras?.attachments, !attachments.isEmpty else { continue }
            out[turn.index] = attachments.map { a in
                let key = [turn.ts ?? "", a.kind, a.name].joined(separator: "\u{1f}")
                let n = seen[key, default: 0]
                seen[key] = n + 1
                return ChatFile(source: source, kind: a.kind, name: a.name, size: a.size, at: turn.ts, n: n)
            }
        }
        return out
    }

    /// A file name as the backend stores it: its last path part, square brackets as round ones (the words carry it
    /// as `[image: name]`), whitespace collapsed, at most 120 characters, "unnamed" when empty.
    static func normalizedName(_ raw: String) -> String {
        let last = raw.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
        let round = last.replacingOccurrences(of: "[", with: "(").replacingOccurrences(of: "]", with: ")")
        let collapsed = round.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let capped = String(collapsed.prefix(nameCap))
        return capped.isEmpty ? "unnamed" : capped
    }

    static let imageExtensions: Set<String> = ["png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "tif",
                                               "tiff", "svg"]
    static let videoExtensions: Set<String> = ["mp4", "mov", "m4v", "webm", "avi", "mkv"]
    static let audioExtensions: Set<String> = ["mp3", "m4a", "wav", "aac", "ogg", "flac", "opus", "caf"]

    /// An attachment's kind from its type, else its name's extension (`turn_extras.kind_for`).
    static func kind(mime: String?, name: String) -> String {
        let m = (mime ?? "").lowercased()
        for kind in ["image", "video", "audio"] where m.hasPrefix(kind + "/") { return kind }
        let ext = name.contains(".") ? (name.split(separator: ".").last.map { $0.lowercased() } ?? "") : ""
        if imageExtensions.contains(ext) { return "image" }
        if videoExtensions.contains(ext) { return "video" }
        if audioExtensions.contains(ext) { return "audio" }
        return "file"
    }

    /// Which file a turn's attachment is: among the chat's files said in the turn's second, in the store's order, the
    /// `n`-th whose kind and name are the attachment's; when the name changed on the way in (the scrub), the `n`-th of
    /// that kind — unless a name no other file in the chat carries (WhatsApp names each file uniquely) points at one
    /// file wherever its time lands. Nil when there is none — the tile is then the placeholder.
    static func pick(_ candidates: [ChatMediaCandidate], file: ChatFile) -> ChatMediaCandidate? {
        let named = candidates.filter { $0.name == file.name && $0.kind == file.kind }
        let near = file.instant.map { at in
            candidates.filter { abs($0.date.timeIntervalSince(at)) <= window }
                .sorted { ($0.date, $0.order) < ($1.date, $1.order) }
        } ?? []
        let same = near.filter { $0.name == file.name && $0.kind == file.kind }
        if file.n < same.count { return same[file.n] }
        if named.count == 1, file.name != "unnamed" { return named[0] }
        if same.isEmpty {
            let kind = near.filter { $0.kind == file.kind }
            if file.n < kind.count { return kind[file.n] }
        }
        return nil
    }

    /// "0:07", "4:32", "1:02:03" — a video's or a voice message's length, as the apps say it.
    static func length(_ seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }
}

/// The thumbnails the chat panel drew, outside every bank: `$CICADA_HOME/chat-media/<source>/<chat>/<key>.jpg`
/// (0700 folders, 0600 files), and a Telegram photo opened large beside them. Gone when the chat is unticked
/// (`forget`), and never read for a chat that is not ticked.
enum ChatMediaCache {
    static var root: URL { CicadaRuntime.current.cicadaHome.appendingPathComponent("chat-media", isDirectory: true) }

    static func folder(_ source: ChatMediaSource, root: URL = root) -> URL? {
        guard (16...64).contains(source.chat.count), source.chat.allSatisfy(\.isHexDigit) else { return nil }
        return root.appendingPathComponent(source.channel.rawValue, isDirectory: true)
            .appendingPathComponent(source.chat, isDirectory: true)
    }

    static func file(_ source: ChatMediaSource, key: String, ext: String = "jpg", root: URL = root) -> URL? {
        guard !key.isEmpty, key.count <= 64, key.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") })
        else { return nil }
        return folder(source, root: root)?.appendingPathComponent("\(key).\(ext)")
    }

    static func read(_ source: ChatMediaSource, key: String, ext: String = "jpg", root: URL = root) -> Data? {
        file(source, key: key, ext: ext, root: root).flatMap { try? Data(contentsOf: $0) }
    }

    @discardableResult
    static func write(_ data: Data, _ source: ChatMediaSource, key: String, ext: String = "jpg",
                      root: URL = root) -> URL? {
        guard let folder = folder(source, root: root), let target = file(source, key: key, ext: ext, root: root) else {
            return nil
        }
        let fm = FileManager.default
        do {
            for dir in [root, root.appendingPathComponent(source.channel.rawValue, isDirectory: true), folder] {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            }
            let tmp = folder.appendingPathComponent(".\(key).\(UUID().uuidString).tmp")
            guard fm.createFile(atPath: tmp.path, contents: data, attributes: [.posixPermissions: 0o600]) else {
                return nil
            }
            if fm.fileExists(atPath: target.path) { try fm.removeItem(at: target) }
            try fm.moveItem(at: tmp, to: target)
            return target
        } catch {
            return nil
        }
    }

    /// Unticking a chat: every thumbnail of it goes. Whether anything was there.
    @discardableResult
    static func forget(_ source: ChatMediaSource, root: URL = root) -> Bool {
        guard let folder = folder(source, root: root), FileManager.default.fileExists(atPath: folder.path) else {
            return false
        }
        return (try? FileManager.default.removeItem(at: folder)) != nil
    }

    /// The ticks as the backend answered them: every kept chat of `channel` not among them goes (an untick made on
    /// another device, or before this app ran). Returns how many chats' thumbnails went.
    @discardableResult
    static func keepOnly(_ channel: ChatMediaSource.Channel, ticked: Set<String>, root: URL = root) -> Int {
        let folder = root.appendingPathComponent(channel.rawValue, isDirectory: true)
        guard let chats = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else { return 0 }
        var gone = 0
        for chat in chats where !ticked.contains(chat) {
            if forget(ChatMediaSource(channel: channel, chat: chat), root: root) { gone += 1 }
        }
        return gone
    }
}
