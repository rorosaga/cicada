import Foundation

/// G133 — the app-side twin of `folder_source.glob_match` / `is_included` /
/// `authorship_for`. Two implementations of one matcher is the drift risk, so
/// `FolderGlobTests` runs the SAME table `api/tests/test_folder_source.py`'s
/// `GLOB_TABLE` runs: change one, change both.
enum FolderGlob {
    /// `**/` = any number of directories (none included), `**` = anything,
    /// `*` = anything but `/`, `?` = one character but `/`, anchored.
    static func regexSource(_ pattern: String) -> String {
        let chars = Array(pattern)
        var out = ""
        var i = 0
        while i < chars.count {
            if chars[i] == "*", i + 1 < chars.count, chars[i + 1] == "*" {
                if i + 2 < chars.count, chars[i + 2] == "/" {
                    out += "(?:.*/)?"
                    i += 3
                } else {
                    out += ".*"
                    i += 2
                }
            } else if chars[i] == "*" {
                out += "[^/]*"
                i += 1
            } else if chars[i] == "?" {
                out += "[^/]"
                i += 1
            } else {
                out += NSRegularExpression.escapedPattern(for: String(chars[i]))
                i += 1
            }
        }
        return "^" + out + "$"
    }

    static func compile(_ pattern: String) -> NSRegularExpression? {
        try? NSRegularExpression(pattern: regexSource(pattern))
    }

    static func matches(_ pattern: String, _ relpath: String) -> Bool {
        guard let rx = compile(pattern) else { return false }
        return CompiledFolderRules.hit(rx, relpath)
    }
}

/// One folder's include / exclude / authorship rules, compiled once per scan.
/// `@unchecked Sendable`: `NSRegularExpression` matching is thread-safe, and a
/// scan runs off the main actor.
struct CompiledFolderRules: @unchecked Sendable {
    private let include: [NSRegularExpression]
    private let exclude: [NSRegularExpression]
    private let rules: [(NSRegularExpression, String)]

    init(include: [String], exclude: [String], authorship: [FolderAuthorshipRule]) {
        self.include = include.compactMap(FolderGlob.compile)
        self.exclude = exclude.compactMap(FolderGlob.compile)
        self.rules = authorship.compactMap { rule in FolderGlob.compile(rule.glob).map { ($0, rule.authorship) } }
    }

    init(_ folder: FolderRegistration) {
        self.init(include: folder.include, exclude: folder.exclude, authorship: folder.authorship)
    }

    static func hit(_ rx: NSRegularExpression, _ text: String) -> Bool {
        rx.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }

    func included(_ relpath: String) -> Bool {
        include.contains { Self.hit($0, relpath) } && !exclude.contains { Self.hit($0, relpath) }
    }

    /// A directory whose every descendant is excluded — the walk skips it rather
    /// than descending into a `node_modules` it would then discard file by file.
    func excludesDirectory(_ relpath: String) -> Bool {
        exclude.contains { Self.hit($0, relpath + "/_") }
    }

    /// First matching rule wins; no match is the person's own words.
    func authorship(_ relpath: String) -> String {
        rules.first { Self.hit($0.0, relpath) }?.1 ?? "user"
    }
}
