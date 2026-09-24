import Foundation

/// Round-4 D5 (R-FA15) — "Set up Claude": merge Cicada's MCP server into Claude desktop's config. MERGE, never
/// replace: every other server and setting stays; a file Cicada cannot read is left exactly as it was; the file is
/// backed up before the first write that changes it. The app writes only what it computed itself — the same
/// python / server / memory root as `AgentSetupCatalog` — into the path it computed itself; `GET /agents/setup`'s
/// `config` is never trusted for either.
enum ClaudeDesktopConfig {
    static let key = "cicada"
    static let backupSuffix = ".cicada-backup"

    static func configURL(home: URL = FileManager.default.homeDirectoryForCurrentUser) -> URL {
        home.appendingPathComponent("Library/Application Support/Claude/claude_desktop_config.json")
    }

    static func server(python: String, script: String, memory: String) -> [String: Any] {
        ["command": python, "args": [script], "env": ["CICADA_MEMORY_PATH": memory]]
    }

    enum Reason: Equatable { case notJSON, notAnObject, serversNotAnObject }
    enum Merge: Equatable { case write(Data), unchanged, unparseable(Reason) }
    enum Outcome: Equatable { case done, alreadySetUp, claudeNotSetUp, leftUntouched(Reason), failed(String) }

    static func merge(existing: Data?, server: [String: Any]) -> Merge {
        var root: [String: Any] = [:]
        if let existing, !String(decoding: existing, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            guard let parsed = try? JSONSerialization.jsonObject(with: existing) else { return .unparseable(.notJSON) }
            guard let object = parsed as? [String: Any] else { return .unparseable(.notAnObject) }
            root = object
        }
        var servers: [String: Any] = [:]
        if let raw = root["mcpServers"] {
            guard let object = raw as? [String: Any] else { return .unparseable(.serversNotAnObject) }
            servers = object
        }
        if let current = servers[key] as? [String: Any], NSDictionary(dictionary: current).isEqual(to: server) {
            return .unchanged
        }
        servers[key] = server
        root["mcpServers"] = servers
        guard let data = try? JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .withoutEscapingSlashes])
        else { return .unparseable(.notJSON) }
        return .write(data)
    }

    /// Never creates Claude's folder: a Mac where Claude desktop never ran has nothing to set up yet.
    static func apply(server: [String: Any], at url: URL, fileManager: FileManager = .default) -> Outcome {
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: url.deletingLastPathComponent().path, isDirectory: &isDirectory),
              isDirectory.boolValue else { return .claudeNotSetUp }
        let existing = fileManager.contents(atPath: url.path)
        switch merge(existing: existing, server: server) {
        case .unchanged: return .alreadySetUp
        case .unparseable(let why): return .leftUntouched(why)
        case .write(let data):
            do {
                if let existing { try existing.write(to: URL(fileURLWithPath: url.path + backupSuffix), options: .atomic) }
                // Through a symlink, never over it: an atomic write replaces the path it is given, and a config kept
                // in a dotfiles repo is a link the person made (R-FA15, "merge never replace").
                try data.write(to: url.resolvingSymlinksInPath(), options: .atomic)
                return .done
            } catch {
                return .failed(error.localizedDescription)
            }
        }
    }
}
