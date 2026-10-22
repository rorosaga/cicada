import Foundation

/// Search & files (owner, 2026-10-14) — one place to choose what Cicada can look through: the folders it keeps, and
/// how well search understands what it finds. The owner's brief: "without mentioning embeddings. All of this
/// technical stuff had to be abstracted." Every string a person sees on the page by default is in `defaultVisible`,
/// which `SearchFilesTests.testDefaultVisibleWordsAreNeverTechnical` holds to the page's bar (no model, embedding,
/// index, vector, token, runtime or checksum). There is no *Advanced* any more (settings defaults, owner 2026-10-22):
/// the version picker and the rebuild left the app for `cicada index`. The hidden Settings-search keywords stay technical on purpose so a technical search still lands here.
///
/// Honest state over the mock (REVIEW §5): a folder today is read into memory (G133), so a row says *Kept in memory*
/// and counts notes — never a kind count or a search-only depth that nothing computes yet (G195). *Understand images*
/// says what it does today: Looks are found by what they show.
extension Copy {
    enum SearchFiles {
        // MARK: The page
        static let sidebar = "Search & files"
        static let pageTitle = "What Cicada can look through"
        static let subtitle = "Folders it reads, and how well search understands them."
        /// "Settings → Search & files" — the pointer every other surface uses (`CopyConstantsTests`).
        static let pointer = "\(Copy.settings) → \(sidebar)"

        // MARK: Folders
        static let foldersGroup = "Folders"
        static let checkingFolders = "Checking your folders…"
        static let foldersEmptyTitle = "No folders yet"
        static let foldersEmptyDetail = "Pick a folder of notes and Cicada keeps what you write there in memory. Edits reach it on their own."
        static let addFolder = "Add a folder…"
        static let addFolderDetail = "Notes you write there are kept in memory, and edits reach it on their own."
        static let addFolderDemoHelp = "Folders are added to your own memory, not the demo."
        static let addFolderPanel = "Choose a folder of notes to keep in memory"
        /// The row's depth, in words (owner ruling: one list, two depths). Today every folder has this one; G195 adds
        /// a search-only depth beside it.
        static let depthMemory = "Kept in memory"
        static let depthMemoryHelp = "Sleep reads the notes you write here and learns from them."
        static let notReadYet = "Not read yet"
        static func notes(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "note" : "notes")"
        }
        static let manage = "Manage"
        static let readNow = "Read now"
        static let readNowHelp = "Read the folder again now. Edits also arrive on their own."
        static let readNowAway = "This folder isn't on this Mac, so it can't be read from here."
        static let readingNow = "Reading now…"
        static let stopWatching = "Stop watching"
        static let save = "Save"
        static let choose = "Choose…"
        static let lookInside = "Look inside"
        static let startWatching = "Start watching"
        static func stopWatchingTitle(_ name: String) -> String { "Stop watching \(name)?" }
        static let stopWatchingKeeps = "Everything Cicada already learned from this folder stays in your memory."
        /// How much of it Sleep will read — a count of notes, never a count of passes nobody can picture.
        static func sleepWillRead(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            n == 0 ? "Nothing here for Sleep to read yet — an agent's notes are kept, not read."
                : "Sleep will read \(notes(n, locale: locale)) of your own."
        }

        // MARK: How search understands
        static let understandGroup = "How search understands"
        static let meaningTitle = "Understand what you mean"
        static let imagesTitle = "Understand images"
        static let turnOn = "Turn on"
        static let tryAgain = "Try again"
        static let download = "Download"
        static let on = "On"
        static let sleepRunningHelp = "Sleep is running — change this when it finishes."
        static let downloadRunningHelp = "One download at a time — this one can start when the current one finishes."
        /// Review B2 — a failed re-read says it in the page's own words, never the backend's diagnostic sentence.
        static let rereadFailed = "Search couldn't switch, so it keeps working as before. The next Sleep tries again."

        static func megabytes(_ bytes: Int) -> String {
            "\(UsageFormat.count(max(1, Int((Double(bytes) / 1_000_000).rounded())))) MB"
        }
        /// The built-in version already understands meaning; the download is the sharper one (REVIEW finding 3).
        static func meaningOffer(bytes: Int) -> String {
            bytes > 0
                ? "On, built in. A sharper version finds looser matches, in any language: a one-time download of about \(megabytes(bytes)) that stays on this Mac. Then it re-reads your memory once, in the background."
                : "On, built in. A sharper version finds looser matches, in any language: a one-time download that stays on this Mac. Then it re-reads your memory once, in the background."
        }
        static let meaningTurnOnHelp = "Downloads the sharper version once, then switches search to it."
        static let meaningBuiltIn = "On, built in — quick, and good for most memories."
        static let meaningReadyHere = "On, built in. The sharper version is already on this Mac — turn it on to use it."
        static let meaningUseHelp = "Switches search to the sharper version, which re-reads your memory once."
        static let meaningSharper = "The sharper version, on this Mac."
        static let meaningLarger = "The larger version, on this Mac."
        static let meaningOther = "Searching with a version set up outside the app."
        static func meaningMissing(bytes: Int) -> String {
            bytes > 0
                ? "This memory was set up for sharper search on another Mac. Until you download it here (about \(megabytes(bytes))), search matches your words only."
                : "This memory was set up for sharper search on another Mac. Until you download it here, search matches your words only."
        }
        static let meaningMissingLarger = "This memory was set up for the larger version on another Mac, so search here matches your words only. Turn on the sharper version to search by meaning on this Mac."
        static func downloading(_ step: String) -> String { "\(step). You can close Settings; it keeps going." }
        static let gettingReady = "Getting ready. You can close Settings; it keeps going."
        static func rereading(done: Int, total: Int) -> String {
            total > 0
                ? "Re-reading your memory for sharper matches — step \(done) of \(total). Search keeps working meanwhile."
                : "Re-reading your memory for sharper matches. Search keeps working meanwhile."
        }
        static let waitsForSleep = "Switching waits for Sleep to finish. Search keeps working."
        static let switchesAtNextSleep = "Switches at the next Sleep, which re-reads your memory once."
        static let loadFailed = "Couldn't check how search is set up. Open this page again to retry."

        static func imagesOffer(bytes: Int) -> String {
            bytes > 0
                ? "Find looks by what they show, not only by your notes. About \(megabytes(bytes)), once. It stays on this Mac."
                : "Find looks by what they show, not only by your notes. A one-time download that stays on this Mac."
        }
        static let imagesTurnOnHelp = "Downloads image understanding once. It stays on this Mac; your screenshots never leave it."
        static let imagesWaitsForMeaning = "Find looks by what they show, not only by your notes. Builds on Understand what you mean."
        static let imagesWaitsHelp = "Turn on Understand what you mean first — images build on it."
        static let imagesWaitsForDownload = "Waits for the download above."
        static let imagesWaitsForDownloadHelp = "One download at a time — this one starts when the one above finishes."
        static let imagesOn = "Looks are found by what they show."
        static let imagesUnsupported = "Understanding images needs macOS 15 or later on a Mac with Apple silicon. Words still work."

        /// One line under the two rows: what leaves the Mac (nothing) — true of today's folders and downloads.
        static let privacyLine = "Folders are read on this Mac, and everything search downloads stays here."

        // MARK: Pointers from elsewhere
        static let integrationsLinkLead = "Folders are in"
        static let folderNotSetUpHere = "This folder isn't set up on this Mac yet — open \(pointer) to finish."

        /// Every sentence the page shows, with sample arguments — the lint's input.
        static let defaultVisible: [String] = [
            sidebar, pageTitle, subtitle,
            foldersGroup, checkingFolders, foldersEmptyTitle, foldersEmptyDetail, addFolder, addFolderDetail, addFolderDemoHelp,
            addFolderPanel, depthMemory, depthMemoryHelp, notReadYet, notes(1), notes(312), manage, readNow, readNowHelp,
            readNowAway, readingNow, stopWatching, save, choose, lookInside, startWatching, stopWatchingTitle("Notes"),
            stopWatchingKeeps, sleepWillRead(0), sleepWillRead(12),
            understandGroup, meaningTitle, imagesTitle, turnOn, tryAgain, download, on, sleepRunningHelp,
            meaningOffer(bytes: 585_000_000), meaningOffer(bytes: 0), meaningTurnOnHelp, meaningBuiltIn, meaningReadyHere,
            meaningUseHelp, meaningSharper, meaningLarger, meaningOther, meaningMissing(bytes: 585_000_000),
            meaningMissing(bytes: 0), meaningMissingLarger, downloading("Downloading — 312 of 585 MB"), gettingReady,
            rereading(done: 1, total: 3), rereading(done: 0, total: 0), waitsForSleep, switchesAtNextSleep, loadFailed,
            imagesOffer(bytes: 309_000_000), imagesOffer(bytes: 0), imagesTurnOnHelp, imagesWaitsForMeaning,
            imagesWaitsHelp, imagesWaitsForDownload, imagesWaitsForDownloadHelp, imagesOn, imagesUnsupported,
            privacyLine, downloadRunningHelp, rereadFailed, integrationsLinkLead, folderNotSetUpHere,
        ]
    }
}
