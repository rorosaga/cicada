import Foundation

/// A verified update, copied beside the installed app and waiting for the swap (G182).
struct StagedUpdate: Equatable, Sendable {
    let manifest: UpdateManifest
    /// `<folder>/.Cicada.app.update` — a hidden sibling, so the swap is a rename on one volume.
    let stagedApp: URL
    let installedApp: URL
}

/// What the helper leaves behind for the next launch (G182): `<CICADA_HOME>/update-failed.json` when a swap failed
/// (`installed` absent) or when the swap worked but the background service didn't start again (`installed: true`,
/// `service_stopped: true`).
struct UpdateFailureRecord: Codable, Equatable, Sendable {
    let version: String
    let reason: String
    var installed: Bool?
    var serviceStopped: Bool?

    enum CodingKeys: String, CodingKey {
        case version, reason, installed
        case serviceStopped = "service_stopped"
    }

    init(version: String, reason: String, installed: Bool? = nil, serviceStopped: Bool? = nil) {
        self.version = version
        self.reason = reason
        self.installed = installed
        self.serviceStopped = serviceStopped
    }
}

/// G182 — the helper's notes' one reader. Each is read once, then deleted, so it is said on the launch after it and
/// never again. `update-deferred.json` is the soft one: Sleep was writing when the helper looked, so nothing moved.
enum UpdateFailureMarker {
    static func url(home: URL) -> URL { home.appendingPathComponent("update-failed.json") }
    static func deferredURL(home: URL) -> URL { home.appendingPathComponent("update-deferred.json") }

    static func consume(home: URL, fileManager: FileManager = .default) -> UpdateFailureRecord? {
        guard let data = take(url(home: home), fileManager) else { return nil }
        return try? JSONDecoder().decode(UpdateFailureRecord.self, from: data)
    }

    /// The version whose install waited for Sleep, if the helper deferred one.
    static func consumeDeferral(home: URL, fileManager: FileManager = .default) -> String? {
        struct Deferral: Decodable { let version: String }
        guard let data = take(deferredURL(home: home), fileManager) else { return nil }
        return (try? JSONDecoder().decode(Deferral.self, from: data))?.version
    }

    private static func take(_ file: URL, _ fileManager: FileManager) -> Data? {
        guard let data = fileManager.contents(atPath: file.path) else { return nil }
        try? fileManager.removeItem(at: file)
        return data
    }
}

/// G182 — "is Sleep writing right now?", asked of the backend itself at hand-off rather than read from the Store's
/// cached status (which is nil before the first poll). Busy means `status == "running"` — the gate the app's own
/// write controls use (`ProjectWriteGate`), wider than G177's `writing` because installing stops the backend and
/// would cut a drain between batches too — or `writing == true`. No answer at all (nothing listening, or no reply in
/// time) means no cycle is running there; an answer that can't be read is treated as busy.
enum SleepProbe {
    enum Answer: Equatable, Sendable { case idle, busy, noAnswer, ambiguous }

    static func isBusy(_ answer: Answer) -> Bool { answer == .busy || answer == .ambiguous }

    static func statusURL(port: Int) -> URL { URL(string: "http://127.0.0.1:\(port)/sleep/status")! }

    static func classify(statusCode: Int?, body: Data?, error: Error?) -> Answer {
        if let error {
            if let u = error as? URLError, [.cannotConnectToHost, .timedOut, .networkConnectionLost, .cannotFindHost,
                                              .notConnectedToInternet, .zeroByteResource].contains(u.code) {
                return .noAnswer
            }
            return .ambiguous
        }
        guard statusCode == 200, let body,
              let object = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any],
              let status = object["status"] as? String else { return .ambiguous }
        return status == "running" || (object["writing"] as? Bool) == true ? .busy : .idle
    }

    /// One GET with the backend's bearer token (when the file exists) and the given timeout.
    static func live(port: Int, tokenFile: URL) -> @Sendable (Duration) async -> Answer {
        { timeout in
            let seconds = Double(timeout.components.seconds) + Double(timeout.components.attoseconds) / 1e18
            var request = URLRequest(url: statusURL(port: port), cachePolicy: .reloadIgnoringLocalCacheData,
                                     timeoutInterval: seconds)
            if let raw = try? String(contentsOf: tokenFile, encoding: .utf8) {
                let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
                if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
            }
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = seconds
            config.connectionProxyDictionary = [:]
            let session = URLSession(configuration: config)
            defer { session.finishTasksAndInvalidate() }
            do {
                let (data, response) = try await session.data(for: request)
                return classify(statusCode: (response as? HTTPURLResponse)?.statusCode, body: data, error: nil)
            } catch {
                return classify(statusCode: nil, body: nil, error: error)
            }
        }
    }
}

/// G182 phase 5 — gets a release ready and hands the swap to a helper that outlives the app.
///
/// **Stage** (in the background, while the person keeps working): download the zip into a temporary folder as
/// `Cicada.zip`, verify it (`UpdateVerifier`), unzip it with `ditto`, check that what came out is this app — the same
/// bundle id, a release build, the version the manifest promised, and a signature `codesign --verify --strict --deep`
/// accepts — then copy it to a hidden sibling of the installed app, with the manifest in a sidecar beside it so a
/// deferred install survives a relaunch (`recoverStaged`). Nothing the person runs has changed yet.
///
/// **Hand off** (as the app quits): write a small `/bin/sh` script (`helperScript`, pure and tested) and start it
/// detached (`DetachedSpawn`). It waits for this process to exit, asks the backend whether Sleep is writing (and
/// defers if so), stops the background service if one is installed, renames the installed app aside and the staged one
/// into place, moves the old copy to the Trash, starts the service again (three tries), and reopens the app when
/// asked. Any failure puts the old copy back and leaves `update-failed.json`. The new app rewrites `~/.cicada/bin`'s
/// launchers itself when it opens (`LauncherInstaller`), so the helper never touches them.
struct UpdateInstaller: Sendable {
    typealias Download = @Sendable (URLRequest, URL, @escaping @Sendable (Double) -> Void) async throws -> Void
    typealias Spawn = @Sendable ([String]) throws -> Void

    static let unzipTimeout: Duration = .seconds(600)
    static let codesignTimeout: Duration = .seconds(300)
    static let toolEnvironment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin"]
    /// Always this name — never the URL's last path component, which the manifest controls.
    static let downloadName = "Cicada.zip"

    enum Failure: Error, Equatable {
        case folderNotWritable(String)
        case download(String)
        case verify(UpdateVerifier.Failure)
        case unzip
        case noApp
        case wrongApp
        case notRelease
        case wrongVersion(found: String?, expected: String)
        case codesign
        case stage
        case helper(String)

        /// A phrase that follows "Couldn't get the update ready: " (or "Couldn't start the update: ").
        var message: String {
            switch self {
            case .folderNotWritable(let folder): Copy.Updates.reasonFolderNotWritable(folder)
            case .download(let why): why
            case .verify(let f): f.message
            case .unzip: Copy.Updates.reasonUnzip
            case .noApp: Copy.Updates.reasonNoApp
            case .wrongApp: Copy.Updates.reasonWrongApp
            case .notRelease: Copy.Updates.reasonNotRelease
            case .wrongVersion(let found, let expected): Copy.Updates.reasonWrongVersion(found: found, expected: expected)
            case .codesign: Copy.Updates.reasonCodesign
            case .stage: Copy.Updates.reasonStage
            case .helper(let why): Copy.Updates.reasonHelper(why)
            }
        }
    }

    let installedApp: URL
    let bundleIdentifier: String?
    let publicKeyBase64: String?
    let cicadaHome: URL
    let port: Int
    let uid: uid_t
    let pid: Int32
    let launchAgentPlist: URL
    let trashDir: URL
    let workRoot: URL
    let download: Download
    let runner: AgentProcessRunning
    let spawn: Spawn

    init(installedApp: URL, bundleIdentifier: String?, publicKeyBase64: String?, cicadaHome: URL,
         port: Int = CicadaRuntime.defaultPort,
         uid: uid_t = getuid(), pid: Int32 = ProcessInfo.processInfo.processIdentifier,
         launchAgentPlist: URL = BackendAgentPolicy.plistURL(),
         trashDir: URL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".Trash"),
         workRoot: URL = FileManager.default.temporaryDirectory.appendingPathComponent("CicadaUpdate"),
         download: @escaping Download = UpdateDownloader.download,
         runner: AgentProcessRunning = LiveAgentProcessRunner(),
         spawn: @escaping Spawn = DetachedSpawn.run) {
        self.installedApp = installedApp.standardizedFileURL
        self.bundleIdentifier = bundleIdentifier
        self.publicKeyBase64 = publicKeyBase64
        self.cicadaHome = cicadaHome
        self.port = port
        self.uid = uid
        self.pid = pid
        self.launchAgentPlist = launchAgentPlist
        self.trashDir = trashDir
        self.workRoot = workRoot
        self.download = download
        self.runner = runner
        self.spawn = spawn
    }

    // MARK: Paths

    static func stagedURL(installedApp: URL) -> URL {
        installedApp.deletingLastPathComponent().appendingPathComponent(".\(installedApp.lastPathComponent).update")
    }

    static func backupURL(installedApp: URL) -> URL {
        installedApp.deletingLastPathComponent().appendingPathComponent(".\(installedApp.lastPathComponent).old")
    }

    /// `.Cicada.app.update.json` — the staged copy's manifest, so a relaunch can adopt it without a new download.
    static func sidecarURL(stagedApp: URL) -> URL {
        stagedApp.deletingLastPathComponent().appendingPathComponent(stagedApp.lastPathComponent + ".json")
    }

    var logFile: URL { cicadaHome.appendingPathComponent("logs/update.log") }
    var helperPIDFile: URL { cicadaHome.appendingPathComponent("update-helper.pid") }
    var tokenFile: URL { cicadaHome.appendingPathComponent("api_token") }

    // MARK: Stage

    /// Download, verify, unzip, validate, copy beside the installed app. Throws `Failure` in plain words; the
    /// temporary folder is removed on every path.
    func stage(_ manifest: UpdateManifest, progress: @escaping @Sendable (Double) -> Void) async throws -> StagedUpdate {
        let fm = FileManager.default
        let folder = installedApp.deletingLastPathComponent()
        // Fail before a byte is downloaded when the swap could never happen.
        guard fm.isWritableFile(atPath: folder.path) else { throw Failure.folderNotWritable(folder.path) }
        do { _ = try UpdateVerifier.publicKey(base64: publicKeyBase64) } catch { throw Failure.verify(.noPublicKey) }

        let work = workRoot.appendingPathComponent(UUID().uuidString)
        try? fm.createDirectory(at: work, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: work) }

        let zip = work.appendingPathComponent(Self.downloadName)
        do {
            try await download(UpdateChecker.request(manifest.url, version: nil), zip, progress)
        } catch {
            throw Failure.download(UpdateChecker.Failure.from(error).message)
        }
        do {
            try UpdateVerifier.verify(file: zip, manifest: manifest, publicKeyBase64: publicKeyBase64)
        } catch let f as UpdateVerifier.Failure {
            throw Failure.verify(f)
        }

        let extracted = work.appendingPathComponent("extracted")
        try? fm.createDirectory(at: extracted, withIntermediateDirectories: true)
        let unzip = await runner.run(["/usr/bin/ditto", "-x", "-k", zip.path, extracted.path],
                                     environment: Self.toolEnvironment, timeout: Self.unzipTimeout)
        guard unzip.status == 0 else { throw Failure.unzip }
        try? fm.removeItem(at: zip)   // ~150 MB the copy below doesn't need

        let apps = ((try? fm.contentsOfDirectory(at: extracted, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension == "app" }
        guard apps.count == 1, let app = apps.first else { throw Failure.noApp }
        try Self.validate(info: Self.info(of: app), bundleIdentifier: bundleIdentifier, version: manifest.version)
        let codesign = await runner.run(["/usr/bin/codesign", "--verify", "--strict", "--deep", app.path],
                                        environment: Self.toolEnvironment, timeout: Self.codesignTimeout)
        guard codesign.status == 0 else { throw Failure.codesign }

        let staged = Self.stagedURL(installedApp: installedApp)
        let sidecar = Self.sidecarURL(stagedApp: staged)
        try? fm.removeItem(at: sidecar)
        if fm.fileExists(atPath: staged.path) { try? fm.removeItem(at: staged) }
        let copy = await runner.run(["/usr/bin/ditto", app.path, staged.path],
                                    environment: Self.toolEnvironment, timeout: Self.unzipTimeout)
        guard copy.status == 0, fm.fileExists(atPath: staged.appendingPathComponent("Contents/Info.plist").path) else {
            try? fm.removeItem(at: staged)
            throw Failure.stage
        }
        // Without the sidecar the copy still installs this session; it just isn't adopted after a relaunch.
        if let data = try? JSONEncoder().encode(manifest) { try? data.write(to: sidecar, options: .atomic) }
        return StagedUpdate(manifest: manifest, stagedApp: staged, installedApp: installedApp)
    }

    static func info(of app: URL) -> [String: Any]? {
        NSDictionary(contentsOf: app.appendingPathComponent("Contents/Info.plist")) as? [String: Any]
    }

    /// The extracted app is this app, a release, at the promised version — anything else is never staged.
    static func validate(info: [String: Any]?, bundleIdentifier: String?, version: String) throws {
        guard let info else { throw Failure.noApp }
        guard let expected = bundleIdentifier, !expected.isEmpty,
              (info["CFBundleIdentifier"] as? String) == expected else { throw Failure.wrongApp }
        guard (info[CicadaRuntime.distributionInfoKey] as? String) == "release" else { throw Failure.notRelease }
        let found = info["CFBundleShortVersionString"] as? String
        guard found == version else { throw Failure.wrongVersion(found: found, expected: version) }
    }

    // MARK: Hand off

    /// Writes the helper and starts it detached. `relaunch` reopens the app after the swap ("Restart to update"); a
    /// quit-time install leaves it closed, as the person asked.
    func handOff(_ staged: StagedUpdate, relaunch: Bool, currentVersion: String?) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: staged.stagedApp.path) else { throw Failure.stage }
        let plan = HelperPlan(
            pid: pid, installedApp: staged.installedApp.path, stagedApp: staged.stagedApp.path,
            backupApp: Self.backupURL(installedApp: staged.installedApp).path, trashDir: trashDir.path,
            version: staged.manifest.version, fromVersion: currentVersion, logFile: logFile.path,
            failureMarker: UpdateFailureMarker.url(home: cicadaHome).path,
            deferredMarker: UpdateFailureMarker.deferredURL(home: cicadaHome).path, pidFile: helperPIDFile.path,
            statusURL: SleepProbe.statusURL(port: port).absoluteString, tokenFile: tokenFile.path,
            launchAgentPlist: fm.fileExists(atPath: launchAgentPlist.path) ? launchAgentPlist.path : nil,
            uid: uid, relaunch: relaunch)
        do {
            try fm.createDirectory(at: workRoot, withIntermediateDirectories: true)
            let script = workRoot.appendingPathComponent("cicada-update-\(UUID().uuidString).sh")
            guard fm.createFile(atPath: script.path, contents: Data(Self.helperScript(plan).utf8),
                                attributes: [.posixPermissions: NSNumber(value: 0o700)]) else {
                throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: script.path])
            }
            try spawn(["/bin/sh", script.path])
        } catch let f as Failure {
            throw f
        } catch {
            throw Failure.helper(error.localizedDescription)
        }
    }

    /// At launch: a staged copy left by a deferred install is adopted — no new download — when its sidecar names a
    /// version newer than the running one and the copy's own Info.plist still says it is this app, a release, at that
    /// version (it was signature-checked when it was staged). Anything else is removed with its sidecar. A copy a
    /// running helper is still using (its PID file names a live process) is left alone and not adopted.
    static func recoverStaged(installedApp: URL, helperPIDFile: URL, bundleIdentifier: String?, currentVersion: String?,
                              isAlive: (pid_t) -> Bool = { kill($0, 0) == 0 },
                              fileManager: FileManager = .default) -> StagedUpdate? {
        if let raw = fileManager.contents(atPath: helperPIDFile.path).map({ String(decoding: $0, as: UTF8.self) }),
           let helper = pid_t(raw.trimmingCharacters(in: .whitespacesAndNewlines)), helper > 0, isAlive(helper) {
            return nil
        }
        let staged = stagedURL(installedApp: installedApp)
        let sidecar = sidecarURL(stagedApp: staged)
        if fileManager.fileExists(atPath: staged.path),
           let data = fileManager.contents(atPath: sidecar.path),
           let manifest = try? JSONDecoder().decode(UpdateManifest.self, from: data),
           let offered = SemVer(manifest.version), let current = currentVersion.flatMap(SemVer.init), offered > current,
           (try? validate(info: info(of: staged), bundleIdentifier: bundleIdentifier, version: manifest.version)) != nil {
            return StagedUpdate(manifest: manifest, stagedApp: staged, installedApp: installedApp)
        }
        if fileManager.fileExists(atPath: staged.path) { try? fileManager.removeItem(at: staged) }
        try? fileManager.removeItem(at: sidecar)
        return nil
    }

    // MARK: The helper script

    struct HelperPlan: Equatable, Sendable {
        var pid: Int32
        var installedApp: String
        var stagedApp: String
        var backupApp: String
        var trashDir: String
        var version: String
        var fromVersion: String?
        var logFile: String
        var failureMarker: String
        var deferredMarker: String
        var pidFile: String
        /// `http://127.0.0.1:<port>/sleep/status` — asked once more right before anything moves.
        var statusURL: String
        var tokenFile: String
        /// The background service's plist; nil leaves every `launchctl` line out of the script.
        var launchAgentPlist: String?
        var uid: uid_t
        var relaunch: Bool
    }

    /// Half a second per poll; 120 polls is the minute the helper waits for the app to exit.
    static let quitPolls = 120
    /// launchd can refuse a bootstrap that races its own bootout: `install-backend-agent.sh`'s three tries, 1 s apart.
    static let bootstrapTries = 3

    /// The helper, as text. Every path is single-quoted (`LauncherInstaller.singleQuoted`, an embedded `'` spelled
    /// `'\''`); versions pass through `SemVer`, so only digits and dots reach the script and its JSON.
    ///
    /// - **Before anything moves:** the staged copy must still be there (an install script may have removed it — then
    ///   the helper steps aside quietly, no marker, no relaunch), the app must have exited (a minute at most), and the
    ///   backend must not be running a cycle (`curl` with the bearer token fed on stdin, never in argv). A cycle defers
    ///   the install: nothing moves, the staged copy stays for the next quit, `update-deferred.json` says why.
    /// - **The swap** is two renames inside the app's own folder (atomic on one volume): installed → `.Cicada.app.old`,
    ///   staged → installed. If something else put an app at the installed path in between, that app is left in place
    ///   and the helper steps aside. Only after the swap does the old copy go to the Trash — a move that may cross
    ///   volumes and may fail (the copy stays beside the app; the log says so).
    /// - **TERM** (logout, shutdown) puts the old copy back when it is out of place and restarts the service.
    /// - **The service** restarts with three tries; a service that won't start is written into `update-failed.json`
    ///   (`service_stopped`) so the next launch repairs it.
    static func helperScript(_ plan: HelperPlan) -> String {
        let q = LauncherInstaller.singleQuoted
        let version = SemVer(plan.version)?.description ?? "unknown"
        let from = plan.fromVersion.flatMap(SemVer.init)?.description ?? "unknown"
        let domain = "gui/\(plan.uid)"
        let sidecar = sidecarURL(stagedApp: URL(fileURLWithPath: plan.stagedApp)).path
        var s = """
        #!/bin/sh
        # Cicada updater (G182) — written by Cicada.app as it quits, run once, detached from it.
        # Waits for the app to exit, swaps in the verified copy staged beside it, and moves the old copy to the Trash.
        # On any failure the old copy goes back where it was and the reason is left for the app to show once.
        trap '' HUP INT
        pid=\(plan.pid)
        app=\(q(plan.installedApp))
        staged=\(q(plan.stagedApp))
        sidecar=\(q(sidecar))
        backup=\(q(plan.backupApp))
        trash=\(q(plan.trashDir))
        log=\(q(plan.logFile))
        marker=\(q(plan.failureMarker))
        deferred=\(q(plan.deferredMarker))
        pidfile=\(q(plan.pidFile))
        statusurl=\(q(plan.statusURL))
        tokenfile=\(q(plan.tokenFile))
        version=\(q(version))
        relaunch=\(plan.relaunch ? 1 : 0)
        booted=0

        """
        if let plist = plan.launchAgentPlist {
            s += """
            plist=\(q(plist))
            service=\(q("\(domain)/\(BackendAgentPolicy.label)"))

            """
        }
        s += """
        /bin/mkdir -p "$(/usr/bin/dirname "$log")" "$(/usr/bin/dirname "$marker")"
        echo "$$" > "$pidfile"
        say() { printf '%s %s\\n' "$(/bin/date '+%Y-%m-%dT%H:%M:%S%z')" "$1" >> "$log"; }

        """
        if plan.launchAgentPlist != nil {
            s += """
            start_service() {
              if [ "$booted" != 1 ]; then return 0; fi
              booted=0
              tries=0
              while [ "$tries" -lt \(bootstrapTries) ]; do
                if /bin/launchctl bootstrap \(q(domain)) "$plist" >> "$log" 2>&1; then
                  say "started the background service again"
                  return 0
                fi
                tries=$((tries + 1))
                if [ "$tries" -lt \(bootstrapTries) ]; then /bin/sleep 1; fi
              done
              say "the background service did not start again"
              return 1
            }

            """
        } else {
            s += """
            start_service() { return 0; }

            """
        }
        s += """
        finish() {
          /bin/rm -f "$pidfile"
          if [ "$relaunch" = 1 ]; then /usr/bin/open "$app" >> "$log" 2>&1; fi
          /bin/rm -f "$0"
          exit "$1"
        }
        fail() {
          say "update to $version failed: $1"
          svc=''
          start_service || svc=', "service_stopped": true'
          printf '{"version": "%s", "reason": "%s"%s}\\n' "$version" "$1" "$svc" > "$marker"
          /bin/rm -rf "$staged" "$sidecar"
          finish 1
        }
        step_aside() {
          say "$1; leaving it be"
          start_service || :
          /bin/rm -f "$pidfile" "$0"
          exit 0
        }
        on_term() {
          say "stopped by the system"
          if [ ! -e "$app" ] && [ -d "$backup" ]; then /bin/mv "$backup" "$app" && say "put the old copy back"; fi
          start_service || :
          /bin/rm -f "$pidfile"
          exit 143
        }
        trap on_term TERM
        sleep_busy() {
          if [ -r "$tokenfile" ]; then
            answer=$(printf 'header = "Authorization: Bearer %s"\\n' "$(/bin/cat "$tokenfile")" | /usr/bin/curl -fsS --noproxy '*' --max-time 2 -K - "$statusurl" 2>/dev/null)
          else
            answer=$(/usr/bin/curl -fsS --noproxy '*' --max-time 2 "$statusurl" 2>/dev/null)
          fi
          code=$?
          case "$code" in
            0) ;;
            7|28|52|56) return 1 ;;
            *) return 0 ;;
          esac
          answer=$(printf '%s' "$answer" | /usr/bin/tr -d ' \\n')
          case "$answer" in
            *'"writing":true'*|*'"status":"running"'*) return 0 ;;
            *'"status":'*) return 1 ;;
            *) return 0 ;;
          esac
        }

        say \(q("updating from \(from) to \(version)"))
        if [ ! -d "$staged" ]; then step_aside "the new copy is gone"; fi
        waited=0
        while kill -0 "$pid" 2>/dev/null; do
          if [ "$waited" -ge \(quitPolls) ]; then fail \(q(Copy.Updates.helperDidNotQuit)); fi
          /bin/sleep 0.5
          waited=$((waited + 1))
        done
        if [ ! -d "$staged" ]; then step_aside "the new copy is gone"; fi
        if sleep_busy; then
          say "Sleep is writing; the update waits for the next quit"
          printf '{"version": "%s"}\\n' "$version" > "$deferred"
          finish 0
        fi

        """
        if plan.launchAgentPlist != nil {
            s += """
            if [ -f "$plist" ] && /bin/launchctl bootout "$service" >> "$log" 2>&1; then
              booted=1
              say "stopped the background service"
            fi

            """
        }
        s += """
        /bin/rm -rf "$backup"
        if ! /bin/mv "$app" "$backup"; then fail \(q(Copy.Updates.helperMoveAside)); fi
        if [ -e "$app" ]; then
          /bin/mkdir -p "$trash"
          /bin/mv "$backup" "$trash/Cicada $(/bin/date '+%Y-%m-%d %H.%M.%S').app" >> "$log" 2>&1 || :
          /bin/rm -rf "$staged" "$sidecar"
          step_aside "another copy of Cicada was put in place meanwhile"
        fi
        if ! /bin/mv "$staged" "$app"; then
          if [ ! -e "$app" ]; then /bin/mv "$backup" "$app" || say "the old copy could not be put back; it is at $backup"; fi
          fail \(q(Copy.Updates.helperMoveIn))
        fi
        /bin/rm -f "$marker" "$deferred" "$sidecar"
        say "installed $version"
        if ! start_service; then
          printf '{"version": "%s", "reason": "%s", "installed": true, "service_stopped": true}\\n' "$version" \(q(Copy.Updates.helperServiceDidNotStart)) > "$marker"
        fi
        /bin/mkdir -p "$trash"
        /bin/mv "$backup" "$trash/Cicada $(/bin/date '+%Y-%m-%d %H.%M.%S').app" >> "$log" 2>&1 || say "the old copy stays at $backup"
        finish 0

        """
        return s
    }
}

/// G182 — starts the helper so it outlives the app. `posix_spawn` with `POSIX_SPAWN_SETSID` puts it in a session and
/// process group of its own, so nothing aimed at the app's group (a terminal's hang-up, launchd tidying the app's job)
/// reaches it; when the app exits it is re-parented to launchd and keeps running. Every inherited descriptor is closed
/// (`POSIX_SPAWN_CLOEXEC_DEFAULT`; stdin/out/err are `/dev/null`, the script logs to its own file), every signal is
/// back to its default (the app ignores SIGTERM for `TerminateOnSignal`, and a helper must not inherit that), and the
/// environment is a fixed PATH and HOME. Never waited on: the app quits right after.
enum DetachedSpawn {
    struct Failed: Error, LocalizedError {
        let code: Int32
        var errorDescription: String? { String(cString: strerror(code)) }
    }

    static let run: UpdateInstaller.Spawn = { argv in
        precondition(!argv.isEmpty)
        var attr: posix_spawnattr_t?
        posix_spawnattr_init(&attr)
        defer { posix_spawnattr_destroy(&attr) }
        let flags = POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK
        posix_spawnattr_setflags(&attr, Int16(flags))
        var noSignals = sigset_t()
        posix_spawnattr_setsigmask(&attr, &noSignals)
        var allSignals = ~sigset_t()
        posix_spawnattr_setsigdefault(&attr, &allSignals)

        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", O_WRONLY, 0)
        posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", O_WRONLY, 0)

        let env = ["PATH=/usr/bin:/bin:/usr/sbin:/sbin", "HOME=\(NSHomeDirectory())"]
        let cArgs = argv.map { strdup($0) } + [nil]
        let cEnv = env.map { strdup($0) } + [nil]
        defer {
            cArgs.forEach { free($0) }
            cEnv.forEach { free($0) }
        }
        var pid: pid_t = 0
        let rc = posix_spawn(&pid, argv[0], &actions, &attr, cArgs, cEnv)
        guard rc == 0 else { throw Failed(code: rc) }
    }
}

/// G182 — the zip's download, with progress, straight to a file (a 150 MB body never sits in memory). An ephemeral
/// session: no cookies, nothing cached. Only `UpdateInstaller` calls it, after the person's switch or click.
final class UpdateDownloader: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private let destination: URL
    private let progress: @Sendable (Double) -> Void
    private var continuation: CheckedContinuation<Void, Error>?
    private var moveError: Error?
    private let lock = NSLock()

    private init(destination: URL, progress: @escaping @Sendable (Double) -> Void) {
        self.destination = destination
        self.progress = progress
    }

    static let download: UpdateInstaller.Download = { request, destination, progress in
        let delegate = UpdateDownloader(destination: destination, progress: progress)
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 60
        let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let task = session.downloadTask(with: request)
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                delegate.lock.lock()
                delegate.continuation = c
                delegate.lock.unlock()
                task.resume()
            }
        } onCancel: {
            task.cancel()
        }
    }

    private func finish(_ error: Error?) {
        lock.lock()
        let c = continuation
        continuation = nil
        lock.unlock()
        if let error { c?.resume(throwing: error) } else { c?.resume() }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        progress(min(1, Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)))
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // The file at `location` is gone when this returns, so it moves now.
        if let http = downloadTask.response as? HTTPURLResponse, http.statusCode != 200 {
            moveError = UpdateChecker.Failure.http(http.statusCode)
            return
        }
        do {
            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.moveItem(at: location, to: destination)
        } catch {
            moveError = error
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        finish(error ?? moveError)
    }
}
