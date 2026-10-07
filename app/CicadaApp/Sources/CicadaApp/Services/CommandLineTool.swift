import Foundation

/// What *Install the command-line tool* would link to (G180, TODO ruling 21).
enum CommandLineToolTarget: Equatable {
    case available(URL)
    /// Why nothing can be linked yet — said in the row instead of a button that would claim success.
    case unavailable(String)
}

/// Where `~/.local/bin/cicada` stands, as the Settings row says it.
enum CommandLineToolState: Equatable {
    case notInstalled
    /// The link resolves to this runtime's launcher. `onPath` is whether the person's shell seems to look in
    /// `~/.local/bin` (`ShellPath`); when not, the row shows the one line to add.
    case installed(onPath: Bool)
    /// A working `cicada` that is not this runtime's (another checkout, another install): left alone.
    case elsewhere(String)
    /// Something that is not a link and not a command is at that path: left alone.
    case blocked
    case unavailable(String)
    case failed(String)
}

/// G180 unit 3 — *Install the command-line tool*: one link, `~/.local/bin/cicada`, no admin (ruling 21). The target
/// follows the runtime: a release links its stable `~/.cicada/bin/cicada` launcher (which `LauncherInstaller` rewrites
/// on every launch), and only once that launcher exists and the app runs from a real folder; a developer build links
/// its checkout's `scripts/cicada` (it never writes `~/.cicada/bin`). A missing path or a dangling link is
/// (re)written; a link that already works, or anything that is not a link, is left alone and named — the same rules as
/// `scripts/install-cli.sh` (`make cli`). Every input is injectable so tests never touch a real home.
enum CommandLineTool {
    static func linkPath(home: URL) -> URL {
        home.appendingPathComponent(".local/bin/cicada")
    }

    static func target(isRelease: Bool, launchersAreStable: Bool, binDir: URL, codeRoot: URL,
                       fileManager: FileManager = .default) -> CommandLineToolTarget {
        if isRelease {
            guard launchersAreStable else { return .unavailable(Copy.cliToolMoveApp) }
            let launcher = binDir.appendingPathComponent("cicada")
            return fileManager.isExecutableFile(atPath: launcher.path) ? .available(launcher)
                : .unavailable(Copy.cliToolWaitForLauncher)
        }
        let script = codeRoot.appendingPathComponent("scripts/cicada")
        return fileManager.isExecutableFile(atPath: script.path) ? .available(script)
            : .unavailable(Copy.cliToolNoCheckoutLauncher)
    }

    static func target(runtime: CicadaRuntime, fileManager: FileManager = .default) -> CommandLineToolTarget {
        target(isRelease: runtime.isRelease, launchersAreStable: runtime.launchersAreStable, binDir: runtime.binDir,
               codeRoot: runtime.codeRoot, fileManager: fileManager)
    }

    static func state(target: CommandLineToolTarget, home: URL, onPath: Bool,
                      fileManager: FileManager = .default) -> CommandLineToolState {
        guard case .available(let launcher) = target else {
            if case .unavailable(let why) = target { return .unavailable(why) }
            return .notInstalled
        }
        let link = linkPath(home: home)
        var info = stat()
        guard lstat(link.path, &info) == 0 else { return .notInstalled }
        if (info.st_mode & S_IFMT) == S_IFLNK {
            // `fileExists` follows the link: false means nothing works through it (dangling).
            guard fileManager.fileExists(atPath: link.path) else { return .notInstalled }
            let resolved = link.resolvingSymlinksInPath().standardizedFileURL.path
            return resolved == launcher.resolvingSymlinksInPath().standardizedFileURL.path
                ? .installed(onPath: onPath) : .elsewhere(resolved)
        }
        let isRegular = (info.st_mode & S_IFMT) == S_IFREG
        return isRegular && fileManager.isExecutableFile(atPath: link.path) ? .elsewhere(link.path) : .blocked
    }

    /// What is at the link path, as install decides on it. Absent and dangling stay distinct (G180 review): only a
    /// dangling symlink Settings saw may be replaced, and only if it is still that same symlink.
    private enum Entry: Equatable {
        case absent
        case dangling(ino: UInt64, dev: Int32)
        case present
    }

    private static func entry(_ path: String, fileManager: FileManager) -> Entry {
        var info = stat()
        guard lstat(path, &info) == 0 else { return errno == ENOENT ? .absent : .present }
        if (info.st_mode & S_IFMT) == S_IFLNK, !fileManager.fileExists(atPath: path) {
            return .dangling(ino: UInt64(info.st_ino), dev: Int32(info.st_dev))
        }
        return .present
    }

    /// Links only when nothing works there yet; every other state is returned as it is. Never deletes or replaces
    /// an entry it did not see: an absent path gets `symlink(2)`, which fails rather than overwrite something that
    /// appeared meanwhile (then the row re-reads and names it); a dangling link is moved aside atomically and
    /// unlinked only if it is still the very symlink Settings saw (same inode) — anything else is put back. Nothing is
    /// ever removed recursively.
    @discardableResult
    static func install(target: CommandLineToolTarget, home: URL, onPath: Bool,
                        fileManager: FileManager = .default) -> CommandLineToolState {
        let current = state(target: target, home: home, onPath: onPath, fileManager: fileManager)
        guard current == .notInstalled, case .available(let launcher) = target else { return current }
        let link = linkPath(home: home)
        let observed = entry(link.path, fileManager: fileManager)
        guard observed != .present else { return current }
        do {
            try fileManager.createDirectory(at: link.deletingLastPathComponent(), withIntermediateDirectories: true)
        } catch {
            return .failed(error.localizedDescription)
        }
        if case .dangling(let ino, let dev) = observed,
           !removeDangling(at: link, ino: ino, dev: dev, fileManager: fileManager) {
            return state(target: target, home: home, onPath: onPath, fileManager: fileManager)   // fail closed
        }
        if symlink(launcher.path, link.path) != 0 {
            let code = errno
            // Something appeared at the path meanwhile: it is kept, and the row says what it is.
            if code == EEXIST { return state(target: target, home: home, onPath: onPath, fileManager: fileManager) }
            return .failed(String(cString: strerror(code)))
        }
        return state(target: target, home: home, onPath: onPath, fileManager: fileManager)
    }

    /// Moves whatever is at `link` aside with `RENAME_EXCL`, then unlinks it only if it is the dangling symlink
    /// Settings saw (same inode and device, still a symlink, still dangling). Otherwise it goes back where it was;
    /// if that name was taken in the meantime it stays, untouched, beside it. True only when the link is gone.
    private static func removeDangling(at link: URL, ino: UInt64, dev: Int32, fileManager: FileManager) -> Bool {
        let aside = link.deletingLastPathComponent().appendingPathComponent(".cicada.\(UUID().uuidString).aside")
        guard renamex_np(link.path, aside.path, UInt32(RENAME_EXCL)) == 0 else { return false }
        var info = stat()
        let same = lstat(aside.path, &info) == 0 && (info.st_mode & S_IFMT) == S_IFLNK
            && UInt64(info.st_ino) == ino && Int32(info.st_dev) == dev && !fileManager.fileExists(atPath: aside.path)
        if same, unlink(aside.path) == 0 { return true }
        _ = renamex_np(aside.path, link.path, UInt32(RENAME_EXCL))
        return false
    }

    /// This Mac, this runtime, this person's home — what the Settings row shows.
    static func current(fileManager: FileManager = .default) -> (CommandLineToolTarget, URL, Bool) {
        let home = fileManager.homeDirectoryForCurrentUser
        let onPath = ShellPath.includesLocalBin(home: home, appPath: ProcessInfo.processInfo.environment["PATH"] ?? "")
        return (target(runtime: .current, fileManager: fileManager), home, onPath)
    }
}

/// Whether the person's shell seems to look in `~/.local/bin`. The app's own PATH is launchd's, not the shell's, so
/// this reads the shell's profile files and `/etc/paths` — it never runs a shell. A line counts when it is not a
/// comment and names `.local/bin`; the row says "seems", because a profile can build PATH in ways a read can't see.
enum ShellPath {
    static let profiles = [".zshenv", ".zprofile", ".zshrc", ".bash_profile", ".bashrc", ".profile",
                           ".config/fish/config.fish"]

    static func includesLocalBin(home: URL, appPath: String,
                                 read: (URL) -> String? = { try? String(contentsOf: $0, encoding: .utf8) }) -> Bool {
        let local = home.appendingPathComponent(".local/bin").path
        if appPath.split(separator: ":").contains(where: { $0 == local || $0 == "~/.local/bin" }) { return true }
        let files = [URL(fileURLWithPath: "/etc/paths")] + profiles.map { home.appendingPathComponent($0) }
        return files.contains { file in
            guard let text = read(file) else { return false }
            return text.split(separator: "\n").contains { line in
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                return !trimmed.hasPrefix("#") && trimmed.contains(".local/bin")
            }
        }
    }
}
