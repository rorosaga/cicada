import Foundation
import Observation

// Ruling 84 (2026-11-26) — the folders Cicada's own agent may read: `GET/PUT/POST /settings/agent-folders`. The rule on the
// backend proposes (a notes folder, documents) and the person disposes: a switch per folder, and a folder of their own added by
// hand. The backend keeps the choice per device outside every bank. Not a Store domain (no ETag): read when Settings appears,
// held in memory, a switch written optimistically and put back with the server's sentence on a refusal. The app only picks the
// folder with the system panel and sends its path; it never reads the folder, and the list shows names, never paths.

struct AgentReadFolder: Decodable, Equatable, Identifiable {
    var id: String
    var name: String
    /// `default`, `on`, `off`, `refused` or `protected`.
    var state: String
    /// The rule's own verdict: `protected` for a folder macOS keeps closed, `system` for the Mac's own (never named to the person).
    var why: String
    var granted: Bool
    var locked: Bool
    var added: Bool
    /// The reason in the backend's words: why it is on, why it is off.
    var reason: String

    enum CodingKeys: String, CodingKey { case id, name, state, why, granted, locked, added, reason }

    init(id: String, name: String, state: String, why: String = "", granted: Bool, locked: Bool = false, added: Bool = false, reason: String = "") {
        self.id = id
        self.name = name
        self.state = state
        self.why = why
        self.granted = granted
        self.locked = locked
        self.added = added
        self.reason = reason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "refused"
        why = try c.decodeIfPresent(String.self, forKey: .why) ?? ""
        granted = try c.decodeIfPresent(Bool.self, forKey: .granted) ?? false
        locked = try c.decodeIfPresent(Bool.self, forKey: .locked) ?? false
        added = try c.decodeIfPresent(Bool.self, forKey: .added) ?? false
        reason = try c.decodeIfPresent(String.self, forKey: .reason) ?? ""
    }
}

struct AgentReadFoldersResponse: Decodable, Equatable {
    var folders: [AgentReadFolder]

    init(folders: [AgentReadFolder] = []) { self.folders = folders }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        folders = try c.decodeIfPresent([AgentReadFolder].self, forKey: .folders) ?? []
    }

    enum CodingKeys: String, CodingKey { case folders }

    /// The folders the list draws: every one but a folder macOS keeps closed (those are one sentence under the list), and
    /// a folder that is Cicada's own or too large to check is shown with its switch off and unavailable.
    var shown: [AgentReadFolder] { folders.filter { $0.state != "protected" } }

    /// The names of the folders macOS keeps closed to a read the backend starts by itself, as the backend names them.
    var protectedNames: [String] { folders.filter { $0.state == "protected" && $0.why != "system" }.map(\.name) }

    /// The same list with one switch moved: what the row shows before the server answers.
    func setting(_ id: String, on: Bool) -> AgentReadFoldersResponse {
        var copy = self
        guard let index = copy.folders.firstIndex(where: { $0.id == id }), !copy.folders[index].locked else { return copy }
        copy.folders[index].state = on ? "on" : "off"
        copy.folders[index].granted = on
        return copy
    }
}

/// Settings → Privacy & data → the agent's folders. One load, one optimistic write at a time.
@Observable
@MainActor
final class AgentReadFoldersModel {
    struct Deps {
        var load: () async throws -> AgentReadFoldersResponse
        var set: (String, Bool) async throws -> AgentReadFoldersResponse
        var add: (String) async throws -> AgentReadFoldersResponse
        var remove: (String) async throws -> AgentReadFoldersResponse

        static let live = Deps(
            load: { try await APIClient.shared.fetchAgentReadFolders() },
            set: { id, on in try await APIClient.shared.setAgentReadFolder(id, on: on) },
            add: { path in try await APIClient.shared.addAgentReadFolder(path: path) },
            remove: { id in try await APIClient.shared.removeAgentReadFolder(id) })
    }

    private(set) var list: AgentReadFoldersResponse?
    private(set) var busy: Set<String> = []
    /// The server's sentence when a change was refused; cleared by the next change.
    private(set) var note: String?
    private(set) var loadFailed = false
    @ObservationIgnored private let deps: Deps

    init(deps: Deps = .live) { self.deps = deps }

    func load() async {
        do {
            list = try await deps.load()
            loadFailed = false
        } catch {
            // The last good list stays (never blank); only a first load that failed says so.
            loadFailed = list == nil
        }
    }

    func set(_ id: String, on: Bool) async {
        guard let before = list, !busy.contains(id) else { return }
        note = nil
        list = before.setting(id, on: on)
        busy.insert(id)
        defer { busy.remove(id) }
        do {
            list = try await deps.set(id, on)
        } catch {
            list = before
            note = Self.sentence(error)
        }
    }

    /// The path comes from the system folder panel; the backend resolves it and answers with a reason when it can never be read.
    func add(path: String) async {
        note = nil
        do {
            list = try await deps.add(path)
        } catch {
            note = Self.sentence(error)
        }
    }

    func remove(_ id: String) async {
        note = nil
        do {
            list = try await deps.remove(id)
        } catch {
            note = Self.sentence(error)
        }
    }

    /// The backend's own sentence (a refusal's `detail` is written for the person), else this list's.
    static func sentence(_ error: Error) -> String {
        if case APIError.httpError(_, let body) = error, let text = ProjectWriteFailure.detail(body) { return text }
        return Copy.AgentReadFolders.saveFailed
    }
}
