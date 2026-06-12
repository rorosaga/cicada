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

    func fetchEntity(id: String) async throws -> Entity {
        return try await get("/entities/\(id)")
    }

    func fetchEntityHistory(id: String) async throws -> [EntityHistoryEntry] {
        return try await get("/entities/\(id)/history")
    }

    // MARK: - Nudges

    func fetchNudges() async throws -> [Nudge] {
        return try await get("/nudges")
    }

    func resolveNudge(id: String, action: String, answer: String? = nil) async throws {
        var body: [String: Any] = ["action": action]
        if let answer { body["answer"] = answer }
        try await post("/nudges/\(id)/resolve", body: body)
    }

    // MARK: - Clarifications

    func fetchClarifications() async throws -> [Clarification] {
        return try await get("/clarifications")
    }

    func resolveClarification(id: String, action: String, answer: String? = nil, mergeTarget: String? = nil) async throws {
        var body: [String: Any] = ["action": action]
        if let answer { body["answer"] = answer }
        if let mergeTarget { body["mergeTarget"] = mergeTarget }
        try await post("/clarifications/\(id)", body: body)
    }

    // MARK: - Status (menu-bar tamagotchi)

    /// Fetch the aggregate status snapshot for the menu-bar bookworm. Tries the
    /// unified `GET /status` endpoint (owned by the inbox axis); if that endpoint
    /// is not yet merged (404) it composes the same struct client-side from the
    /// legacy endpoints that exist today. Flipping fully to `/status` later means
    /// deleting the fallback branch — nothing else changes.
    func fetchStatus() async throws -> StatusSnapshot {
        do {
            return try await get("/status")
        } catch let APIError.httpError(code, _) where code == 404 {
            return try await composeStatus()
        }
    }

    /// Client-side compose fallback: assemble a ``StatusSnapshot`` from the
    /// endpoints that ship today. Issues the calls concurrently and degrades
    /// gracefully if any individual call fails (missing pieces fall back to
    /// neutral values rather than failing the whole snapshot).
    private func composeStatus() async throws -> StatusSnapshot {
        async let sleepTask = tryFetch { try await self.fetchSleepStatus() }
        async let nudgesTask = tryFetch { try await self.fetchNudges() }
        async let clarTask = tryFetch { try await self.fetchClarifications() }
        async let episodesTask = tryFetch { try await self.fetchEpisodeQueue() }
        async let scheduleTask = tryFetch { try await self.fetchSchedule() }
        async let historyTask = tryFetch { try await self.fetchSleepHistory() }

        let sleep = await sleepTask
        let nudges = await nudgesTask ?? []
        let clarifications = await clarTask ?? []
        let episodes = await episodesTask ?? []
        let schedule = await scheduleTask
        let history = await historyTask ?? []

        let byKind = Self.inboxByKind(nudges: nudges, clarifications: clarifications)
        let total = byKind.values.reduce(0, +)

        let unprocessed = episodes.filter { !$0.processed }.count
        let lastIngestedAt = episodes
            .map(\.timestamp)
            .max()   // ISO8601 strings sort lexicographically by time

        let lastSleepAt = Self.lastSleepISO(from: history)
        let nextSleepAt = Self.nextSleepISO(from: schedule)

        return StatusSnapshot(
            sleep: StatusSnapshot.Sleep(
                status: sleep?.status ?? "idle",
                stage: sleep?.stage ?? 0,
                totalStages: sleep?.totalStages ?? 5,
                cycleId: sleep?.cycleId,
                error: sleep?.error
            ),
            inbox: StatusSnapshot.Inbox(total: total, byKind: byKind),
            episodes: StatusSnapshot.Episodes(unprocessed: unprocessed, lastIngestedAt: lastIngestedAt),
            lastSleepAt: lastSleepAt,
            nextSleepAt: nextSleepAt
        )
    }

    /// Post a clipboard URL to the media/sources ingest endpoint. The endpoint
    /// ships in a later wave; callers handle a 404 as "coming soon".
    func saveSource(url: String) async throws {
        try await post("/sources/save", body: ["url": url])
    }

    private func fetchSleepHistory() async throws -> [SleepHistoryEntry] {
        return try await get("/sleep/history")
    }

    /// Run an async fetch and swallow errors into `nil` so a single missing
    /// legacy endpoint never sinks the whole composed snapshot.
    private func tryFetch<T>(_ op: () async throws -> T) async -> T? {
        try? await op()
    }

    private static func inboxByKind(nudges: [Nudge], clarifications: [Clarification]) -> [String: Int] {
        var byKind: [String: Int] = [:]
        for n in nudges {
            byKind[n.type.rawValue, default: 0] += 1
        }
        if !clarifications.isEmpty {
            byKind["clarification", default: 0] += clarifications.count
        }
        return byKind
    }

    /// Most-recent "Sleep cycle" commit date from `/sleep/history` (the endpoint
    /// already filters to sleep commits). History is newest-first, so the first
    /// entry's date is the last sleep.
    private static func lastSleepISO(from history: [SleepHistoryEntry]) -> String? {
        guard let first = history.first else { return nil }
        return normalizeToISO(first.date)
    }

    private static func normalizeToISO(_ raw: String) -> String? {
        // git dates arrive as ISO already in this codebase; pass through if it
        // parses, else hand back the raw string (the menu still renders a
        // best-effort relative time, and parse failures degrade to "never").
        if StatusSnapshot.parseDate(raw) != nil { return raw }
        // Try a common git format: "2026-06-12 03:01:55 +0000".
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd HH:mm:ss Z"
        if let d = fmt.date(from: raw) {
            let iso = ISO8601DateFormatter()
            return iso.string(from: d)
        }
        return raw
    }

    /// Next occurrence of the scheduled hour:minute, or nil if scheduling is
    /// disabled. Computed in local time to match the schedule's clock.
    private static func nextSleepISO(from schedule: ScheduleConfig?) -> String? {
        guard let schedule, schedule.enabled else { return nil }
        var comps = DateComponents()
        comps.hour = schedule.hour
        comps.minute = schedule.minute
        comps.second = 0
        guard let next = Calendar.current.nextDate(
            after: Date(),
            matching: comps,
            matchingPolicy: .nextTime
        ) else { return nil }
        let iso = ISO8601DateFormatter()
        return iso.string(from: next)
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
