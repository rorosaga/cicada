import CryptoKit
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

    /// G234: the first field of a record that is no note — a locked note's id, and the read's own tally. `split` takes
    /// both out, so neither is ever posted in the dump.
    static let lockedMark = "cicada-locked"
    static let statsMark = "cicada-stats"

    /// One batched script: every account → folder, properties fetched in BULK per folder (`id of every note of
    /// fld` is one Apple event for the whole folder, not five per note — a 217-note library blew a 30 s budget
    /// the other way), records gathered in a list and joined once (string concatenation is quadratic). A
    /// per-folder `try` skips a folder Notes cannot read; the inner `try` skips one unreadable note.
    ///
    /// After the folder, each record carries the modification date as `«class isot»` (a locale-free local ISO time —
    /// the human date string above it reads differently in every locale) and the Mac's UTC offset in seconds, so the
    /// backend dates a note when it was written (`notes_sync._DATED_FIELDS`, 2026-10-23); the human `modified` string
    /// stays the backend's dedup key.
    ///
    /// 2026-11-04 — last, the folder's ACCOUNT ("iCloud", "On My Mac", a mail account's name), so the Sources page
    /// browses account → folder → notes (`notes_sync._ACCOUNT_FIELDS`); never part of a note's dedup key.
    ///
    /// G234 (owner: "locked notes must be unavailable to read") — every property of a note is asked through `whose
    /// password protected is false`, evaluated inside Notes, so no event ever names a locked note's `plaintext`, `name`
    /// or dates; filtering a bulk read afterwards would still have requested the body. Measured on macOS 27 on one
    /// throwaway note: the filter returns an unlocked note's text, and an empty match is an empty list, not an error.
    /// A locked note gives only its id (`lockedMark` records), which is what lets the backend retire what it already
    /// kept. The bulk lists are separate events, so the ids are read again last: if a note was locked, unlocked, added
    /// or removed in between, the lists no longer line up and the folder waits for the next read rather than risk one
    /// note's text under another's id. A folder that cannot be read at all is counted (`statsMark`).
    ///
    /// Measured 2026-11-04 on a throwaway note: **locking gives a note a new id**, while its name and both dates survive.
    /// So what Cicada kept under the old id is found by those three instead: read here, hashed by `lockedKeys`, and
    /// the name and dates never leave the app. A locked note's `plaintext` is returned in full while it is open in the
    /// session and `password protected` stays true, which is why the filter is what keeps it out.
    static let script = """
    set FS to (ASCII character 30)
    set RS to (ASCII character 29)
    set utcOffset to (time to GMT) as string
    set outList to {}
    set readFolders to 0
    set failedFolders to 0
    tell application "Notes"
        repeat with acc in accounts
            set accName to ""
            try
                set accName to name of acc as string
            end try
            repeat with fld in folders of acc
                try
                    set lockedIds to id of (every note of fld whose password protected is true)
                    set lockedNames to name of (every note of fld whose password protected is true)
                    set lockedCreated to creation date of (every note of fld whose password protected is true)
                    set lockedModified to modification date of (every note of fld whose password protected is true)
                    repeat with i from 1 to count of lockedIds
                        set end of outList to "\(lockedMark)" & FS & (item i of lockedIds as string) & FS & (item i of lockedNames as string) & FS & (item i of lockedCreated as string) & FS & (item i of lockedModified as string)
                    end repeat
                    set folderName to name of fld as string
                    set noteIds to id of (every note of fld whose password protected is false)
                    set noteNames to name of (every note of fld whose password protected is false)
                    set noteBodies to plaintext of (every note of fld whose password protected is false)
                    set cDates to creation date of (every note of fld whose password protected is false)
                    set mDates to modification date of (every note of fld whose password protected is false)
                    set idsAfter to id of (every note of fld whose password protected is false)
                    if idsAfter = noteIds then
                        repeat with i from 1 to count of noteIds
                            try
                                set end of outList to (item i of noteIds as string) & FS & (item i of noteNames as string) & FS & (item i of noteBodies as string) & FS & (item i of cDates as string) & FS & (item i of mDates as string) & FS & folderName & FS & ((item i of mDates) as «class isot» as string) & FS & utcOffset & FS & accName
                            end try
                        end repeat
                    end if
                    set readFolders to readFolders + 1
                on error
                    set failedFolders to failedFolders + 1
                end try
            end repeat
        end repeat
    end tell
    set end of outList to "\(statsMark)" & FS & (readFolders as string) & FS & (failedFolders as string)
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
        let parts = split(try await read(run: run))
        // G234: every folder refused means the read itself failed (a Notes without the filter, say): an empty post
        // would say "no notes" while the row says it synced.
        if parts.foldersRead == 0, parts.foldersFailed > 0 { throw ReadError.failed }
        return try await APIClient.shared.syncNotes(dump: parts.dump, accounts: parts.accounts, locked: parts.locked,
                                                    lockedKeys: parts.lockedKeys)
    }

    /// 2026-11-04 — the script ends each record with the note's account; it travels BESIDE the dump (`noteAccounts`,
    /// by note id), never in it: a backend that predates it checks a record's field count and would skip every 9-field
    /// record, while it ignores an unknown key. Pure; tested. A record without the field passes through unchanged.
    /// G234: locked ids travel beside it the same way (`lockedNoteIds`), and the read's tally stops here.
    static func split(_ raw: String) -> (dump: String, accounts: [String: String], locked: [String], lockedKeys: [String],
                                         foldersRead: Int, foldersFailed: Int) {
        var accounts: [String: String] = [:]
        var locked: [String] = []
        var lockedKeys: [String] = []
        var foldersRead = 0, foldersFailed = 0
        let records = raw.components(separatedBy: recordSeparator).compactMap { record -> String? in
            var fields = record.components(separatedBy: fieldSeparator)
            if fields.count == 5, fields[0] == lockedMark {
                let id = fields[1].trimmingCharacters(in: .whitespacesAndNewlines)
                if !id.isEmpty, !locked.contains(id) { locked.append(id) }
                for key in [lockedKey(name: fields[2], when: fields[3]), lockedKey(name: fields[2], when: fields[4])]
                where !lockedKeys.contains(key) {
                    lockedKeys.append(key)
                }
                return nil
            }
            if fields.count == 3, fields[0] == statsMark {
                foldersRead = Int(fields[1]) ?? 0
                foldersFailed = Int(fields[2]) ?? 0
                return nil
            }
            guard fields.count == 9 else { return record }
            let account = fields.removeLast().trimmingCharacters(in: .whitespacesAndNewlines)
            let id = fields[0].trimmingCharacters(in: .whitespacesAndNewlines)
            if !id.isEmpty, !account.isEmpty { accounts[id] = account }
            return fields.joined(separator: fieldSeparator)
        }
        return (records.joined(separator: recordSeparator), accounts, locked, lockedKeys, foldersRead, foldersFailed)
    }

    /// `notes_sync.locked_key`: a locked note's name with one of its dates, hashed, so the name never leaves the app.
    static func lockedKey(name: String, when: String) -> String {
        let text = name.trimmingCharacters(in: .whitespacesAndNewlines) + "\u{1F}"
            + when.trimmingCharacters(in: .whitespacesAndNewlines)
        return SHA256.hash(data: Data(text.precomposedStringWithCanonicalMapping.utf8))
            .map { String(format: "%02x", $0) }.joined()
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
