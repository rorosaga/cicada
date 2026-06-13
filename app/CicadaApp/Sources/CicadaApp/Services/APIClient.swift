import Foundation

struct UploadResponse: Codable {
    let status: String
    let episodesCreated: Int
    let duplicatesSkipped: Int
    let message: String
    let source: String
}

struct SleepStatusResponse: Codable {
    let status: String
    let cycleId: String?
    let startedAt: String?
    let progress: String?
    let error: String?
    let indexWarning: String?
    let stage: Int
    let totalStages: Int
    let episodesTotal: Int
    let entitiesCreated: Int
    let entitiesUpdated: Int
    let relationshipsCreated: Int
    let skillsDetected: Int

    enum CodingKeys: String, CodingKey {
        case status, cycleId, startedAt, progress, error, indexWarning, stage, totalStages
        case episodesTotal, entitiesCreated, entitiesUpdated
        case relationshipsCreated, skillsDetected
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(String.self, forKey: .status)
        cycleId = try c.decodeIfPresent(String.self, forKey: .cycleId)
        startedAt = try c.decodeIfPresent(String.self, forKey: .startedAt)
        progress = try c.decodeIfPresent(String.self, forKey: .progress)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        indexWarning = try c.decodeIfPresent(String.self, forKey: .indexWarning)
        stage = try c.decodeIfPresent(Int.self, forKey: .stage) ?? 0
        totalStages = try c.decodeIfPresent(Int.self, forKey: .totalStages) ?? 5
        episodesTotal = try c.decodeIfPresent(Int.self, forKey: .episodesTotal) ?? 0
        entitiesCreated = try c.decodeIfPresent(Int.self, forKey: .entitiesCreated) ?? 0
        entitiesUpdated = try c.decodeIfPresent(Int.self, forKey: .entitiesUpdated) ?? 0
        relationshipsCreated = try c.decodeIfPresent(Int.self, forKey: .relationshipsCreated) ?? 0
        skillsDetected = try c.decodeIfPresent(Int.self, forKey: .skillsDetected) ?? 0
    }
}

struct SleepTriggerResponse: Codable {
    let status: String
    let message: String
    let cycleId: String?
}

struct EpisodeQueueItem: Codable, Identifiable {
    let id: String
    let timestamp: String
    let source: String
    let title: String?
    let preview: String
    let processed: Bool
}

struct ScheduleConfig: Codable, Equatable {
    var enabled: Bool
    var hour: Int
    var minute: Int
}

/// Minimal mirror of the API's `SleepHistoryEntry` (camelCase on the wire). Only
/// `date` is consumed by the status compose fallback; the rest are decoded for
/// completeness so a future caller can reuse the model.
struct SleepHistoryEntry: Codable {
    let commitHash: String
    let date: String
    let message: String
    let filesChanged: [String]
}

enum APIError: Error, LocalizedError {
    case serverUnreachable
    case httpError(Int, String)
    case decodingError(String)

    var errorDescription: String? {
        switch self {
        case .serverUnreachable:
            "Cannot reach Cicada backend"
        case .httpError(let code, let msg):
            "HTTP \(code): \(msg)"
        case .decodingError(let msg):
            "Decoding error: \(msg)"
        }
    }
}

actor APIClient {
    static let shared = APIClient()

    private let baseURL = "http://127.0.0.1:8000"
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    // MARK: - Graph

    func fetchGraph() async throws -> GraphResponse {
        return try await get("/graph")
    }

    // MARK: - Entities

    /// Legacy entity ids can contain `#`, `$`, parens, etc. — `#` silently
    /// truncates the URL into a fragment and other characters nil out
    /// `URL(string:)`, so the id must be percent-encoded as a path component.
    private func encodedID(_ id: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "#$&+,/:;=?@")
        return id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
    }

    func fetchEntity(id: String) async throws -> Entity {
        return try await get("/entities/\(encodedID(id))")
    }

    func fetchEntityHistory(id: String) async throws -> [EntityHistoryEntry] {
        return try await get("/entities/\(encodedID(id))/history")
    }

    // MARK: - Inbox

    /// Fetch the unified inbox (`GET /inbox`). Optionally filter by kinds —
    /// comma-separated on the wire.
    func fetchInbox(kinds: [InboxKind]? = nil) async throws -> [InboxItem] {
        if let kinds, !kinds.isEmpty {
            let q = kinds.map(\.rawValue).joined(separator: ",")
            return try await get("/inbox?kind=\(q)")
        }
        return try await get("/inbox")
    }

    /// Resolve an inbox item. Dispatches server-side on the item's `kind`. The
    /// freetext clarification path sends `{action:"answer", answer:text}` — the
    /// resolution body shape from `api/routers/inbox.py`.
    func resolveInboxItem(
        id: String,
        action: String,
        answer: String? = nil,
        mergeTarget: String? = nil
    ) async throws {
        var body: [String: Any] = ["action": action]
        if let answer { body["answer"] = answer }
        if let mergeTarget { body["mergeTarget"] = mergeTarget }
        try await post("/inbox/\(id)/resolve", body: body)
    }

    // MARK: - Status (menu-bar tamagotchi)

    /// Fetch the aggregate status snapshot (`GET /status`). The endpoint is live
    /// (wave 1); a `StatusSnapshot` decodes straight from the nested
    /// sleep/inbox/episodes wire shape.
    func fetchStatus() async throws -> StatusSnapshot {
        return try await get("/status")
    }

    // MARK: - Sources (media / bookmark ingestion — ships in a later wave)

    /// Post a single URL to the sources ingest endpoint. A 404 means the wave-3
    /// endpoint isn't merged yet; callers surface a friendly "coming soon".
    func saveSource(url: String) async throws {
        try await post("/sources/save", body: ["url": url])
    }

    /// Upload a single source file (bookmarks HTML/JSON, Takeout) to
    /// `POST /sources/upload`. Multipart, same envelope as conversation upload.
    func uploadSource(fileURL: URL) async throws -> UploadResponse {
        return try await uploadMultipart(path: "/sources/upload", fileURL: fileURL)
    }

    /// Shared multipart POST for file ingestion endpoints. Mirrors `uploadFile`
    /// but takes the target path so both `/conversations/upload` and
    /// `/sources/upload` reuse it.
    private func uploadMultipart(path: String, fileURL: URL) async throws -> UploadResponse {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(UploadResponse.self, from: data)
    }

    /// Convenience: upload several source files, aggregating the counts.
    func uploadSources(fileURLs: [URL]) async throws -> UploadResponse {
        var created = 0, skipped = 0
        var lastMessage = ""
        var source = "sources"
        for url in fileURLs {
            let r = try await uploadSource(fileURL: url)
            created += r.episodesCreated
            skipped += r.duplicatesSkipped
            lastMessage = r.message
            source = r.source
        }
        return UploadResponse(
            status: "ok",
            episodesCreated: created,
            duplicatesSkipped: skipped,
            message: lastMessage,
            source: source
        )
    }

    // MARK: - Search (graph toolbar)

    /// Search entities for the graph toolbar (`GET /search`). Returns `[]` on a
    /// 404 so the caller can fall back to a local substring match before the
    /// LEANN endpoint lands.
    func search(q: String, topK: Int = 8) async throws -> [GraphSearchHit] {
        let encoded = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
        let resp: GraphSearchResponse = try await get("/search?q=\(encoded)&top_k=\(topK)&indexes=entities")
        return resp.results
    }

    // MARK: - Sleep

    func fetchSleepStatus() async throws -> SleepStatusResponse {
        return try await get("/sleep/status")
    }

    func triggerSleep() async throws -> SleepTriggerResponse {
        return try await post("/sleep/trigger")
    }

    func fetchEpisodeQueue() async throws -> [EpisodeQueueItem] {
        return try await get("/sleep/episodes")
    }

    func fetchSchedule() async throws -> ScheduleConfig {
        return try await get("/sleep/schedule")
    }

    func updateSchedule(_ cfg: ScheduleConfig) async throws -> ScheduleConfig {
        return try await put("/sleep/schedule", body: [
            "enabled": cfg.enabled,
            "hour": cfg.hour,
            "minute": cfg.minute,
        ])
    }

    // MARK: - Upload

    func uploadFile(fileURL: URL) async throws -> UploadResponse {
        let url = URL(string: "\(baseURL)/conversations/upload")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }

        return try decoder.decode(UploadResponse.self, from: data)
    }

    // MARK: - Generic Helpers

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    @discardableResult
    private func post<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func post(_ path: String, body: [String: Any]? = nil) async throws -> Data {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return data
    }

    private func put<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
}
