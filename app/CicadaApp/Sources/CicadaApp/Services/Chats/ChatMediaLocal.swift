import Foundation

// Chat images (2026-11-04) — the files a ticked chat holds on this Mac, read by the APP from the chat app's own store
// (the backend never opens either path): each attachment's message order and time, its name and kind exactly as the
// backend stored them, and where the file is — resolved inside the app's own folder only (a path that leaves it, or a
// symlink out of it, is no file). Paths stay in the app's memory for the panel's life; none is posted or kept.

extension WhatsAppReader {
    /// The folder WhatsApp keeps a chat's media in is `Message/` under its container; a profile picture's path is
    /// relative to the container itself. Both are tried, inside the container only.
    static let mediaRoots = ["Message", ""]

    /// Every media item of one chat, oldest first (`ZWAMEDIAITEM` joined to its message): the file's own name (the
    /// last part of `ZMEDIALOCALPATH`, else its title — what `whatsapp_source._file` stores), its kind
    /// (`_MEDIA_KIND`, else by name), the file and WhatsApp's own thumbnail where they are on this Mac, and a video's
    /// or a voice message's length (`ZMOVIEDURATION`). A link preview is no attachment and is never listed.
    func media(_ chat: WhatsAppChat) throws -> [ChatMediaCandidate] {
        let rows: [[String: Any]] = try withCopy { db in
            let msg = try Self.columns("ZWAMESSAGE", db)
            let media = try Self.columns("ZWAMEDIAITEM", db)
            guard msg.contains("ZCHATSESSION"), msg.contains("ZMESSAGEDATE"), media.contains("ZMESSAGE") else {
                return []
            }
            let sql = """
                SELECT m.Z_PK AS pk, m.ZMESSAGEDATE AS date,
                       \(Self.pick("ZMESSAGETYPE", from: "m", in: msg, as: "type")),
                       \(Self.pick("ZMEDIALOCALPATH", from: "i", in: media, as: "local")),
                       \(Self.pick("ZTITLE", from: "i", in: media, as: "title")),
                       \(Self.pick("ZXMPPTHUMBPATH", from: "i", in: media, as: "thumb")),
                       \(Self.pick("ZMOVIEDURATION", from: "i", in: media, as: "length"))
                FROM ZWAMESSAGE m JOIN ZWAMEDIAITEM i ON i.ZMESSAGE = m.Z_PK
                WHERE m.ZCHATSESSION = ?1 ORDER BY m.Z_PK
                """
            return try db.query(sql, binds: [.int(chat.sessionPk)])
        }
        let root = containerFolder.resolvingSymlinksInPath().standardizedFileURL
        return rows.compactMap { row -> ChatMediaCandidate? in
            guard let pk = Self.int(row["pk"]), let date = (row["date"] as? NSNumber)?.doubleValue else { return nil }
            let type = Self.int(row["type"]) ?? 0
            guard ![4, 5, 6, 7, 14].contains(type) else { return nil }    // a card, a place, an event, a link, a delete
            let local = (row["local"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let raw = local.map { URL(fileURLWithPath: $0).lastPathComponent } ?? (row["title"] as? String) ?? ""
            let name = ChatMedia.normalizedName(raw)
            let kind = Self.mediaKinds[Int(type)] ?? ChatMedia.kind(mime: nil, name: name)
            let length = (row["length"] as? NSNumber)?.doubleValue
            return ChatMediaCandidate(
                order: pk, date: Date(timeIntervalSinceReferenceDate: date), name: name, kind: kind,
                file: local.flatMap { Self.inside(root, $0) },
                thumbnail: (row["thumb"] as? String).flatMap { $0.isEmpty ? nil : Self.inside(root, $0) },
                length: length.flatMap { $0 > 0 ? $0 : nil })
        }
    }

    /// `whatsapp_source._MEDIA_KIND`.
    static let mediaKinds = [1: "image", 2: "video", 3: "audio", 15: "sticker"]

    /// A store path as a regular file inside the container (under `Message/` or the container itself), or nil.
    static func inside(_ root: URL, _ path: String) -> URL? {
        guard !path.contains("..") else { return nil }
        let bases = path.hasPrefix("/") ? [URL(fileURLWithPath: path)]
            : mediaRoots.map { $0.isEmpty ? root.appendingPathComponent(path) : root.appendingPathComponent($0).appendingPathComponent(path) }
        for base in bases {
            let file = base.resolvingSymlinksInPath().standardizedFileURL
            guard file.path.hasPrefix(root.path + "/"),
                  (try? file.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile == true else { continue }
            return file
        }
        return nil
    }
}

extension MessagesReader {
    /// Where Messages keeps the files: `Attachments/` beside `chat.db` (`attachment.filename` names it as
    /// `~/Library/Messages/Attachments/…`).
    var attachmentsFolder: URL { database.deletingLastPathComponent().appendingPathComponent("Attachments", isDirectory: true) }

    /// Every attachment of one ticked conversation, in the order the backend's sitting lists them (message, then
    /// attachment): the name and kind as `messages_source._file` stores them, and the file where Messages has it on
    /// this Mac (an attachment kept only in iCloud has no file). Read-only, inside one read transaction.
    func media(conversation id: String) throws -> [ChatMediaCandidate] {
        guard let conversation = try conversations(ids: [id]).first else { return [] }
        let db = try open()
        defer { db.close() }
        let rows: [[String: Any]]
        do {
            try db.exec("BEGIN")
            defer { try? db.exec("COMMIT") }
            let sticker = try Self.columns(of: "attachment", in: db).contains("is_sticker")
            rows = try db.query("""
                SELECT m.ROWID AS message, a.ROWID AS attachment, m.date AS date, a.filename AS filename,
                       a.transfer_name AS name, a.mime_type AS mime, a.uti AS uti\(sticker ? ", COALESCE(a.is_sticker, 0) AS sticker" : "")
                FROM attachment a
                JOIN message_attachment_join j ON j.attachment_id = a.ROWID
                JOIN message m ON m.ROWID = j.message_id
                JOIN chat_message_join c ON c.message_id = m.ROWID
                WHERE c.chat_id = ?1 ORDER BY m.ROWID, a.ROWID
                """, binds: [.int(conversation.chatRowId)])
        } catch {
            throw MessagesReadError.unreadable(String(describing: error))
        }
        let root = attachmentsFolder.resolvingSymlinksInPath().standardizedFileURL
        return rows.enumerated().compactMap { index, row -> ChatMediaCandidate? in
            guard let raw = Self.int(row["date"]), raw > 0 else { return nil }
            let seconds = raw > 100_000_000_000 ? Double(raw) / 1e9 : Double(raw)
            let name = ChatMedia.normalizedName((row["name"] as? String) ?? "")
            let kind = (Self.int(row["sticker"]) ?? 0) != 0 ? "sticker"
                : Self.attachmentKind(mime: row["mime"] as? String, uti: row["uti"] as? String)
            return ChatMediaCandidate(order: Int64(index), date: Date(timeIntervalSinceReferenceDate: seconds),
                                      name: name, kind: kind,
                                      file: (row["filename"] as? String).flatMap { attachmentFile($0, root: root) })
        }
    }

    /// `messages_source._attachment_word`: an image, a video or audio by its type, else a file.
    static func attachmentKind(mime: String?, uti: String?) -> String {
        let m = (mime ?? "").lowercased(), u = (uti ?? "").lowercased()
        let hints: [(String, String, [String])] = [
            ("image", "image/", ["public.image", "public.jpeg", "public.png", "public.heic"]),
            ("video", "video/", ["public.movie", "public.mpeg-4"]),
            ("audio", "audio/", ["public.audio", "com.apple.coreaudio"]),
        ]
        for (word, prefix, utis) in hints where m.hasPrefix(prefix) || utis.contains(where: u.contains) { return word }
        return "file"
    }

    /// `attachment.filename` (`~/Library/Messages/Attachments/…`, or the same under the home's absolute path) as a
    /// regular file inside `Attachments/` beside this `chat.db`, or nil.
    func attachmentFile(_ raw: String, root: URL) -> URL? {
        guard !raw.contains("..") else { return nil }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        var rest: String?
        for prefix in ["~/Library/Messages/", home + "/Library/Messages/"] where raw.hasPrefix(prefix) {
            rest = String(raw.dropFirst(prefix.count))
        }
        guard let rest else { return nil }
        let file = database.deletingLastPathComponent().appendingPathComponent(rest)
            .resolvingSymlinksInPath().standardizedFileURL
        guard file.path.hasPrefix(root.path + "/"),
              (try? file.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile == true else { return nil }
        return file
    }
}
