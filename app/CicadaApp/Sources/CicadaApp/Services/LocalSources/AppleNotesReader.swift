import Foundation

/// Apple Notes, read by the APP and parsed by the backend (the `~/Library` rail). The backend used to run this
/// script itself, so macOS asked whether "python3.12" may control Notes — the launchd backend's interpreter, not
/// Cicada — and an "Allow" there reached every script that interpreter ever runs. Run from here, `osascript` is
/// Cicada's child, so the one Automation prompt names Cicada (`NSAppleEventsUsageDescription` in `bundle.sh`).
///
/// One-way and read-only: the script only reads properties. The dump — one `recordSeparator`-joined record per
/// note, fields joined by `fieldSeparator` — is posted as-is to `POST /sources/sync-notes`
/// (`notes_sync.parse_notes_dump`), which scrubs, dedups and writes the episodes.
///
/// Tests never run the real script: it would raise a TCC prompt. `read(run:)` takes the runner as its seam.
enum AppleNotesReader {
    /// `notes_sync.FIELD_SEP` / `RECORD_SEP` — ASCII Record and Group Separators, never typed into a note.
    static let fieldSeparator = "\u{1E}"
    static let recordSeparator = "\u{1D}"

    /// A large library needs real time to serialise plaintext across the Apple Events boundary.
    static let timeout: TimeInterval = 180

    /// One batched script: every account → folder, properties fetched in BULK per folder (`id of every note of
    /// fld` is one Apple event for the whole folder, not five per note — a 217-note library blew a 30 s budget
    /// the other way), records gathered in a list and joined once (string concatenation is quadratic). A
    /// per-folder `try` skips a folder Notes cannot read; the inner `try` skips one unreadable note.
    static let script = """
    set FS to (ASCII character 30)
    set RS to (ASCII character 29)
    set outList to {}
    tell application "Notes"
        repeat with acc in accounts
            repeat with fld in folders of acc
                try
                    set folderName to name of fld as string
                    set noteIds to id of every note of fld
                    set noteNames to name of every note of fld
                    set noteBodies to plaintext of every note of fld
                    set cDates to creation date of every note of fld
                    set mDates to modification date of every note of fld
                    repeat with i from 1 to count of noteIds
                        try
                            set end of outList to (item i of noteIds as string) & FS & (item i of noteNames as string) & FS & (item i of noteBodies as string) & FS & (item i of cDates as string) & FS & (item i of mDates as string) & FS & folderName
                        end try
                    end repeat
                end try
            end repeat
        end repeat
    end tell
    set AppleScript's text item delimiters to RS
    set out to outList as string
    set AppleScript's text item delimiters to ""
    return out
    """

    struct Output: Equatable, Sendable {
        let status: Int32
        let stdout: String
        let stderr: String
        let timedOut: Bool
    }

    typealias Runner = @Sendable (_ script: String, _ timeout: TimeInterval) async -> Output

    enum ReadError: LocalizedError, Equatable {
        case notAllowed
        case timedOut
        case failed

        var errorDescription: String? {
            switch self {
            case .notAllowed:
                "Cicada isn't allowed to read Apple Notes. Turn it on in System Settings → Privacy & Security → "
                    + "Automation → Cicada → Notes, then sync again."
            case .timedOut:
                "Apple Notes took too long to answer. Try again in a moment."
            case .failed:
                "Couldn't read Apple Notes."
            }
        }
    }

    /// The dump, or a sentence the person can act on. Never an empty dump for a refusal: the backend would read
    /// that as "no notes" and the row would say it synced.
    static func read(run: Runner = runOsascript) async throws -> String {
        try outcome(await run(script, timeout)).get()
    }

    /// Read here, then posted — every Sync now and onboarding's tick come through this one path.
    static func syncNow(run: Runner = runOsascript) async throws -> NoteSyncResult {
        try await APIClient.shared.syncNotes(dump: read(run: run))
    }

    /// Pure, so the mapping is tested without a real `osascript`. -1743 is `errAEEventNotPermitted`: the person
    /// said Don't Allow (or turned Cicada off under Automation).
    static func outcome(_ output: Output) -> Result<String, ReadError> {
        if output.timedOut { return .failure(.timedOut) }
        guard output.status == 0 else {
            return .failure(output.stderr.contains("-1743") ? .notAllowed : .failed)
        }
        // `osascript` ends its result with one newline; the dump itself never does.
        var dump = output.stdout
        if dump.hasSuffix("\n") { dump.removeLast() }
        return .success(dump)
    }

    /// `/usr/bin/osascript -e <script>` as a child `Process` (never a shell), through `ChildProcess`: both pipes
    /// drain while it runs — a library's dump is far larger than a pipe's buffer, so reading only at exit would
    /// deadlock. A launch failure reads as status 127, as it always did.
    static let runOsascript: Runner = { script, timeout in
        let out = await ChildProcess.run(URL(fileURLWithPath: "/usr/bin/osascript"), arguments: ["-e", script],
                                         timeout: timeout)
        return Output(status: out.status, stdout: out.stdout, stderr: out.stderr, timedOut: out.timedOut)
    }
}
