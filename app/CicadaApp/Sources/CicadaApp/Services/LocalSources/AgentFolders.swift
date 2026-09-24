import Foundation

/// One line of the "Written by an agent" checklist (R-HS17).
struct AgentFolderRow: Identifiable, Equatable {
    enum Kind: Equatable {
        /// A subfolder, relative to the watched folder: everything below it.
        case folder(String)
        /// A saved rule that is not one folder, kept verbatim so a round trip never drops it.
        case other(String)
    }

    let kind: Kind
    var isOn: Bool

    var glob: String {
        switch kind {
        case .folder(let path): AgentFolders.glob(forSubfolder: path)
        case .other(let rule): rule
        }
    }

    var id: String { glob }

    var title: String {
        switch kind {
        case .folder(let path): Copy.Folders.filesIn(path)
        case .other(let rule): Copy.Folders.filesMatching(rule)
        }
    }
}

/// "Written by an agent" as folders, not globs (the owner's report; R-HS17, G133 R-F2). The wire is
/// unchanged — `FolderAuthorshipRule(glob:authorship: "agent")` — and `<folder>/**` is the glob
/// `FolderGlob` (the backend matcher's twin) matches for everything below that folder. The app reads
/// the folder to list it; the backend never opens it (G133).
enum AgentFolders {
    /// The old default glob was `archive/**`: it is a pre-ticked row when the folder has one, and
    /// nothing when it does not — exactly what the glob matched.
    static let defaultOn: Set<String> = ["archive"]

    static func glob(forSubfolder path: String) -> String {
        path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/**"
    }

    /// The inverse, for Manage: `research/**` → `research`; nil for anything that is not one folder.
    static func subfolder(fromGlob glob: String) -> String? {
        guard glob.hasSuffix("/**") else { return nil }
        let path = String(glob.dropLast(3))
        guard !path.isEmpty, !path.hasPrefix("/"), !path.contains("*"), !path.contains("?") else { return nil }
        return path
    }

    static func initialRows(subfolders: [String]) -> [AgentFolderRow] {
        subfolders.map { AgentFolderRow(kind: .folder($0), isOn: defaultOn.contains($0)) }
    }

    /// Manage's rows: one per subfolder on disk, ticked when a rule names it; then a row for each
    /// saved folder rule not on that list (deeper, or moved); then every other rule, verbatim.
    static func rows(subfolders: [String], globs: [String]) -> [AgentFolderRow] {
        let named = Set(globs.compactMap(subfolder(fromGlob:)))
        var rows = subfolders.map { AgentFolderRow(kind: .folder($0), isOn: named.contains($0)) }
        let listed = Set(subfolders)
        for rule in globs {
            if let path = subfolder(fromGlob: rule) {
                if !listed.contains(path) { rows.append(AgentFolderRow(kind: .folder(path), isOn: true)) }
            } else {
                rows.append(AgentFolderRow(kind: .other(rule), isOn: true))
            }
        }
        return rows
    }

    static func globs(_ rows: [AgentFolderRow]) -> [String] {
        rows.filter(\.isOn).map(\.glob)
    }

    /// "Choose a subfolder…": tick it if listed, else add it ticked.
    static func adding(_ path: String, to rows: [AgentFolderRow]) -> [AgentFolderRow] {
        var out = rows
        if let i = out.firstIndex(where: { $0.kind == .folder(path) }) {
            out[i].isOn = true
        } else {
            out.append(AgentFolderRow(kind: .folder(path), isOn: true))
        }
        return out
    }

    /// A picked folder, relative to the watched one — nil for the folder itself or anything outside it.
    static func relativePath(of url: URL, under root: URL) -> String? {
        let base = root.standardizedFileURL.resolvingSymlinksInPath().pathComponents
        let path = url.standardizedFileURL.resolvingSymlinksInPath().pathComponents
        guard path.count > base.count, Array(path.prefix(base.count)) == base else { return nil }
        return path.dropFirst(base.count).joined(separator: "/")
    }

    /// The watched folder's top-level subfolders, hidden ones skipped, in Finder's order.
    static func subfolders(in root: URL, fileManager: FileManager = .default) -> [String] {
        guard let items = try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey],
                                                               options: [.skipsHiddenFiles]) else { return [] }
        return items
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .map(\.lastPathComponent)
            .sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }
}
