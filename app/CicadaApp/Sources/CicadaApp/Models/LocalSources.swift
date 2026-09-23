import Foundation

/// G133 / R-F2 — whose words the files under `glob` are: `"user"` or `"agent"`.
struct FolderAuthorshipRule: Codable, Equatable, Hashable, Sendable {
    var glob: String
    var authorship: String
}

/// G133 — one watched folder, as `GET /sources/folders` returns it. The backend
/// stamps `device` (R-LS9); the app never sends one. Every field but `id`
/// decodes with a default, so an older or newer backend still yields a row.
struct FolderRegistration: Codable, Identifiable, Equatable, Sendable {
    let id: String
    var label: String
    var path: String
    var device: String
    var include: [String]
    var exclude: [String]
    var authorship: [FolderAuthorshipRule]
    var projectId: String?
    var lastSync: String?
    var papersPending: Bool

    var channelId: String { "folder:\(id)" }

    /// The globs the person marked "written by an agent" (R-F2), for the Manage field.
    var agentGlobs: [String] { authorship.filter { $0.authorship == "agent" }.map(\.glob) }

    enum CodingKeys: String, CodingKey {
        case id, label, path, device, include, exclude, authorship, projectId, lastSync, papersPending
    }

    init(id: String, label: String, path: String, device: String = "", include: [String] = [],
         exclude: [String] = [], authorship: [FolderAuthorshipRule] = [], projectId: String? = nil,
         lastSync: String? = nil, papersPending: Bool = false) {
        self.id = id; self.label = label; self.path = path; self.device = device
        self.include = include; self.exclude = exclude; self.authorship = authorship
        self.projectId = projectId; self.lastSync = lastSync; self.papersPending = papersPending
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
        device = try c.decodeIfPresent(String.self, forKey: .device) ?? ""
        include = try c.decodeIfPresent([String].self, forKey: .include) ?? []
        exclude = try c.decodeIfPresent([String].self, forKey: .exclude) ?? []
        authorship = try c.decodeIfPresent([FolderAuthorshipRule].self, forKey: .authorship) ?? []
        projectId = try c.decodeIfPresent(String.self, forKey: .projectId)
        lastSync = try c.decodeIfPresent(String.self, forKey: .lastSync)
        papersPending = try c.decodeIfPresent(Bool.self, forKey: .papersPending) ?? false
    }
}

struct FolderListResponse: Decodable {
    let folders: [FolderRegistration]
}

struct FolderSyncError: Decodable, Equatable, Sendable {
    let relpath: String
    let reason: String
}

/// `POST /sources/folders/{id}/sync` — every count defaults to zero, so a
/// preview and a real sync decode through one type and batches can be summed.
struct FolderSyncResult: Decodable, Equatable, Sendable {
    var preview = false
    var filesNew = 0
    var filesChanged = 0
    var filesUnchanged = 0
    var filesDeleted = 0
    var agentFiles = 0
    var stage1Passes = 0
    var papersFound = 0
    var created = 0
    var updated = 0
    var renamed = 0
    var tombstoned = 0
    var papersCreated = 0
    var removalsProposed = 0
    var papersPending = false
    var errors: [FolderSyncError] = []

    enum CodingKeys: String, CodingKey {
        case preview, filesNew, filesChanged, filesUnchanged, filesDeleted, agentFiles, stage1Passes
        case papersFound, created, updated, renamed, tombstoned, papersCreated, removalsProposed
        case papersPending, errors
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) throws -> Int { try c.decodeIfPresent(Int.self, forKey: key) ?? 0 }
        preview = try c.decodeIfPresent(Bool.self, forKey: .preview) ?? false
        filesNew = try int(.filesNew); filesChanged = try int(.filesChanged)
        filesUnchanged = try int(.filesUnchanged); filesDeleted = try int(.filesDeleted)
        agentFiles = try int(.agentFiles); stage1Passes = try int(.stage1Passes)
        papersFound = try int(.papersFound); created = try int(.created); updated = try int(.updated)
        renamed = try int(.renamed); tombstoned = try int(.tombstoned)
        papersCreated = try int(.papersCreated); removalsProposed = try int(.removalsProposed)
        papersPending = try c.decodeIfPresent(Bool.self, forKey: .papersPending) ?? false
        errors = try c.decodeIfPresent([FolderSyncError].self, forKey: .errors) ?? []
    }

    /// A preview posted in batches is still one answer to "what is in this folder".
    mutating func add(_ other: FolderSyncResult) {
        filesNew += other.filesNew; filesChanged += other.filesChanged
        filesUnchanged += other.filesUnchanged; filesDeleted += other.filesDeleted
        agentFiles += other.agentFiles; stage1Passes += other.stage1Passes
        papersFound += other.papersFound; created += other.created; updated += other.updated
        renamed += other.renamed; tombstoned += other.tombstoned
        papersCreated += other.papersCreated; removalsProposed += other.removalsProposed
        papersPending = papersPending || other.papersPending
        errors += other.errors
    }
}

/// G134 — per memory. Dictation is opt-in (R-LS23); `ownerSpeakerNames` is the
/// only way a meeting speaker is ever the owner (R-LS22).
struct WisprFlowSettings: Codable, Equatable, Sendable {
    var enabled = false
    var includeDictation = false
    var ownerSpeakerNames: [String] = []

    enum CodingKeys: String, CodingKey { case enabled, includeDictation, ownerSpeakerNames }

    init(enabled: Bool = false, includeDictation: Bool = false, ownerSpeakerNames: [String] = []) {
        self.enabled = enabled; self.includeDictation = includeDictation; self.ownerSpeakerNames = ownerSpeakerNames
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        includeDictation = try c.decodeIfPresent(Bool.self, forKey: .includeDictation) ?? false
        ownerSpeakerNames = try c.decodeIfPresent([String].self, forKey: .ownerSpeakerNames) ?? []
    }
}

struct WisprFlowSyncResult: Decodable, Equatable, Sendable {
    var created = 0
    var updated = 0
    var skipped = 0
    var tombstoned = 0
    var dictationRefused = 0
    var todoClaims = 0

    enum CodingKeys: String, CodingKey { case created, updated, skipped, tombstoned, dictationRefused, todoClaims }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = try c.decodeIfPresent(Int.self, forKey: .created) ?? 0
        updated = try c.decodeIfPresent(Int.self, forKey: .updated) ?? 0
        skipped = try c.decodeIfPresent(Int.self, forKey: .skipped) ?? 0
        tombstoned = try c.decodeIfPresent(Int.self, forKey: .tombstoned) ?? 0
        dictationRefused = try c.decodeIfPresent(Int.self, forKey: .dictationRefused) ?? 0
        todoClaims = try c.decodeIfPresent(Int.self, forKey: .todoClaims) ?? 0
    }
}
