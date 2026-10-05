import Foundation

/// G182 — the stable launchers in `~/.cicada/bin`. A release build's agents, hooks and background service never name
/// a path inside `Cicada.app`: they run `~/.cicada/bin/cicada-*`, and each launch of the app rewrites those four
/// small scripts to point at the copy that opened last. Moving the app, or replacing it with an update, breaks
/// nothing; opening it again repairs everything. A developer build never writes here (its shapes name the checkout).
enum LauncherInstaller {
    /// The script for one entry point. The bundle path is single-quoted with an embedded `'` spelled `'\''` (the
    /// `SnippetEscape.shell` idiom), so a path with a space or a quote is one word. The message names the path the
    /// person can check; `127` is the shell's own "not found".
    static func launcherScript(name: String, bundlePath: String, port: Int, home: String? = nil) -> String {
        let target = CicadaRuntime.bundledBin(bundlePath: bundlePath).appendingPathComponent(name).path
        return """
        #!/bin/sh
        # Cicada launcher — rewritten by Cicada.app each time it opens, pointing at the copy that opened last (G182).
        # Agents, hooks and the background service run this stable path, so moving or updating the app never breaks them.
        target=\(singleQuoted(target))
        if [ ! -x "$target" ]; then
          echo \(singleQuoted("Cicada isn't at \(bundlePath) any more. Open Cicada again and it will repair this launcher.")) >&2
          exit 127
        fi
        : "${CICADA_PORT:=\(port)}"; export CICADA_PORT
        \(home.map { ": \"${CICADA_HOME:=\(doubleQuotedValue($0))}\"; export CICADA_HOME\n" } ?? "")exec "$target" "$@"

        """
    }

    /// A value inside `"${VAR:=…}"`: double-quote context, so `\`, `"`, `$` and a backtick are escaped.
    static func doubleQuotedValue(_ s: String) -> String {
        var out = ""
        for c in s {
            if "\\\"$`".contains(c) { out.append("\\") }
            out.append(c)
        }
        return out
    }

    static func singleQuoted(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: #"'\''"#) + "'"
    }

    enum Outcome: Equatable {
        /// A developer build: nothing written.
        case skipped
        /// The launchers rewritten (by name); empty when every one already matched.
        case wrote([String])
        case failed(String)
    }

    /// Writes each launcher whose content differs, mode 0755, through a temp file in `binDir` and `rename(2)`, so an
    /// agent starting mid-write runs either the old script or the new one, never half of one. Errors are reported,
    /// never thrown: a launcher that cannot be written must not stop the app opening.
    @discardableResult
    static func install(runtime: CicadaRuntime, fileManager: FileManager = .default) -> Outcome {
        // A developer build writes nothing; neither does a copy macOS runs from a temporary place (G182 review,
        // finding 4) — its launchers would point at a path gone after the next reboot or eject.
        guard runtime.isRelease, runtime.launchersAreStable else { return .skipped }
        let binDir = runtime.binDir
        do {
            try fileManager.createDirectory(at: binDir, withIntermediateDirectories: true)
            var wrote: [String] = []
            for name in CicadaRuntime.launcherNames {
                let url = binDir.appendingPathComponent(name)
                let body = Data(launcherScript(name: name, bundlePath: runtime.bundlePath, port: runtime.port,
                                                     home: runtime.cicadaHome.path).utf8)
                let mode = (try? fileManager.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber)?.intValue
                if fileManager.contents(atPath: url.path) == body, mode == 0o755 { continue }
                let temp = binDir.appendingPathComponent(".\(name).\(UUID().uuidString).tmp")
                guard fileManager.createFile(atPath: temp.path, contents: body,
                                             attributes: [.posixPermissions: NSNumber(value: 0o755)]) else {
                    throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: temp.path])
                }
                // `createFile`'s mode is filtered by the umask; set it again so the launcher is always executable.
                try fileManager.setAttributes([.posixPermissions: NSNumber(value: 0o755)], ofItemAtPath: temp.path)
                if Darwin.rename(temp.path, url.path) != 0 {
                    let why = String(cString: strerror(errno))
                    try? fileManager.removeItem(at: temp)
                    throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: url.path,
                                                                    NSLocalizedFailureReasonErrorKey: why])
                }
                wrote.append(name)
            }
            return .wrote(wrote)
        } catch {
            print("Cicada launchers not written: \(error.localizedDescription)")
            return .failed(error.localizedDescription)
        }
    }
}
