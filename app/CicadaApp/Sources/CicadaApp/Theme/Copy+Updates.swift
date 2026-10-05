import Foundation

/// G182 phase 5 — the in-app updater's words (DR-59: sentence case, plain verbs, no "!"). Provider-neutral: the
/// update server is "the update server", never a company's name. Its own file for the reason `Copy+Lists.swift` gives.
/// A `reason…` is a phrase that follows a colon — lower case, no closing period — so one sentence builder ends it.
extension Copy {
    enum Updates {
        // The app menu (right after About Cicada).
        static let menuItem = "Check for Updates…"

        // Settings → General, beside Version.
        static let autoTitle = "Install updates automatically"
        static func autoDetail(automatic: Bool) -> String {
            automatic ? "Cicada looks for a new version every few hours and gets it ready in the background."
                : "Cicada looks only when you choose \(menuItem) in the Cicada menu."
        }
        static let download = "Download"
        static func downloadHelp(_ version: String) -> String { "Download version \(version) and get it ready to install" }
        static let restart = "Restart to update"
        static func restartHelp(_ version: String) -> String { "Quit Cicada, install version \(version) and open it again" }
        static let waitForSleep = "Wait for Sleep to finish — updating restarts Cicada."
        static let whatsNew = "What's new"
        static let whatsNewHelp = "Open the release notes in your browser"

        // The one status line, by state.
        static let checking = "Checking for updates…"
        static func upToDate(checked ago: String) -> String { "Cicada is up to date — checked \(ago)." }
        static func available(_ version: String) -> String { "Version \(version) is available." }
        static func downloading(_ version: String, percent: Int) -> String {
            "Downloading version \(version)… \(percent)%"
        }
        static func ready(_ version: String) -> String { "Version \(version) is ready. It installs when you quit Cicada." }
        /// The helper found Sleep writing when it looked, so nothing moved; the staged copy waits for the next quit.
        static func readyAfterDeferral(_ version: String) -> String {
            "Sleep was writing when Cicada quit, so version \(version) waited. It installs the next time you quit Cicada."
        }
        /// "Restart to update" asked the backend and Sleep had started meanwhile.
        static func readyButSleeping(_ version: String) -> String {
            "Version \(version) is ready. Sleep is writing, so restart once it finishes."
        }
        static func installing(_ version: String) -> String {
            "Installing version \(version)… Cicada opens again in a moment."
        }
        static func needsNewerMacOS(_ version: String, minimum: String) -> String {
            "Version \(version) needs macOS \(minimum) or later."
        }
        static func checkFailed(_ reason: String) -> String { "Couldn't check for updates: \(phrase(reason))." }
        static func downloadFailed(_ reason: String) -> String { "Couldn't get the update ready: \(phrase(reason))." }
        static func installStartFailed(_ reason: String) -> String { "Couldn't start the update: \(phrase(reason))." }
        /// The swap that failed while Cicada was closed (`update-failed.json`), said once on the next launch. A swap
        /// that worked but left the background service stopped says that instead.
        static func installFailed(_ record: UpdateFailureRecord, current: String?) -> String {
            if record.installed == true { return installedServiceStopped(record.version) }
            let head = "The update to \(record.version) couldn't be installed: \(phrase(record.reason))."
            return current.map { "\(head) You're still on \($0)." } ?? head
        }

        static func installedServiceStopped(_ version: String) -> String {
            "Version \(version) is installed, but the background service didn't start again. Turn it on under "
                + "\(Copy.whenClosedGroup)."
        }

        /// A reason as the middle of a sentence: trimmed, without its own closing period.
        static func phrase(_ reason: String) -> String {
            var s = reason.trimmingCharacters(in: .whitespacesAndNewlines)
            while s.hasSuffix(".") { s.removeLast() }
            return s.isEmpty ? "something went wrong" : s
        }

        // Reasons — checking.
        static let reasonNoRepo = "this copy of Cicada doesn't say where its updates come from"
        static let reasonNoRelease = "no version has been published yet"
        static func reasonHTTP(_ code: Int) -> String { "the update server answered with error \(code)" }
        static let reasonNoManifest = "the newest release has no update information"
        static let reasonBadManifest = "the update information couldn't be read"
        static let reasonBadVersion = "this copy of Cicada doesn't know its own version"
        static let reasonInsecure = "the update address isn't a secure one"
        static let reasonForeignURL = "the update address isn't one of the release's own files"
        static let reasonOffline = "this Mac seems to be offline"
        static let reasonUnreachable = "the update server didn't answer"

        // Reasons — getting it ready.
        static let reasonNoKey = "this copy of Cicada has no key to check updates with"
        static let reasonUnreadable = "the download couldn't be read"
        static let reasonWrongSize = "the download is the wrong size"
        static let reasonHashMismatch = "the download doesn't match what was published"
        static let reasonBadSignature = "the download's signature doesn't match, so it was not installed"
        static func reasonFolderNotWritable(_ folder: String) -> String {
            "this account can't change the folder Cicada is in (\(folder)). Move Cicada to a folder you can change, "
                + "such as Applications in your home folder"
        }
        static let reasonUnzip = "the download couldn't be opened"
        static let reasonNoApp = "the download has no Cicada inside"
        static let reasonWrongApp = "the download is a different app"
        static let reasonNotRelease = "the download isn't a release build"
        static func reasonWrongVersion(found: String?, expected: String) -> String {
            "the download is version \(found ?? "unknown"), not \(expected)"
        }
        static let reasonCodesign = "macOS couldn't verify the new copy's signature"
        static let reasonStage = "the new copy couldn't be put beside the old one"
        static func reasonHelper(_ why: String) -> String { "the installer couldn't start (\(phrase(why)))" }

        // Reasons the helper writes into `update-failed.json` (no `"` or `\`: they go into JSON as they are).
        static let helperDidNotQuit = "Cicada didn't quit within a minute"
        static let helperNoStaged = "the new copy was missing"
        static let helperMoveAside = "the installed copy couldn't be moved aside"
        static let helperMoveIn = "the new copy couldn't be moved into place"
        static let helperServiceDidNotStart = "the background service didn't start again"

        /// The line under *Install updates automatically*, computed when read (DR-58): "checked 2 hours ago" is true
        /// at the moment the row renders. nil before the first check.
        /// `deferredVersion` is the version the helper left waiting because Sleep was writing; `sleepRefused` is a
        /// "Restart to update" the backend's fresh answer turned down.
        static func statusLine(_ state: UpdateState, now: Date, deferredVersion: String? = nil, sleepRefused: Bool = false,
                               locale: Locale = .autoupdatingCurrent) -> String? {
            switch state {
            case .idle: return nil
            case .checking: return checking
            case .upToDate(let at):
                let f = RelativeDateTimeFormatter()
                f.locale = locale
                f.unitsStyle = .full
                // `.named`, so a check a moment ago reads "now" rather than "in 0 seconds".
                f.dateTimeStyle = .named
                let ago = now.timeIntervalSince(at) < 60 ? f.localizedString(fromTimeInterval: 0)
                    : f.localizedString(for: at, relativeTo: now)
                return upToDate(checked: ago)
            case .available(let m): return available(m.version)
            case .needsNewerMacOS(let m, let minimum): return needsNewerMacOS(m.version, minimum: minimum)
            case .downloading(let m, let progress):
                return downloading(m.version, percent: Int((min(max(progress, 0), 1) * 100).rounded(.down)))
            case .ready(let m):
                if sleepRefused { return readyButSleeping(m.version) }
                if deferredVersion == m.version { return readyAfterDeferral(m.version) }
                return ready(m.version)
            case .installing(let m): return installing(m.version)
            case .failed(let line): return line
            }
        }
    }
}
