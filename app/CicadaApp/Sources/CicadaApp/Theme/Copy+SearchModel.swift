import Foundation

/// G182 phase 3, reworded for Search & files (owner, 2026-10-14) — the *Advanced* half of Settings → Search & files:
/// the *Search version* picker and the larger version's account sheet. The default-visible half (the two consent rows)
/// is `Copy.SearchFiles`. Provider-neutral (owner, 2026-09-30): the step is described, never a provider doing it;
/// Hugging Face is named only where the person must use their own account there. A version's own label ("Built in",
/// "Sharper", "Larger") comes from the backend's catalog, the person's choice.
extension Copy {
    enum SearchModel {
        // MARK: Advanced → Search version
        static let title = "Search version"
        static let pickerHelp = "How search matches what you mean, not only the words you type."
        static let sleepRunningHelp = "Sleep is running — change this when it finishes."
        static let anotherModel = "another version"
        static let usesOther = "Searching with a version set up outside the app."
        static func builtWithMissing(_ label: String) -> String {
            "This memory was set up for the \(label) version on another Mac. Until you download it here, search matches your words only."
        }
        static func usesNow(_ label: String, detail: String) -> String {
            detail.isEmpty ? "Searching with \(label)." : "Searching with \(label). \(detail)"
        }
        static func switchesAtNextSleep(_ label: String) -> String {
            "Switches to \(label) at the next Sleep, which re-reads your memory once."
        }
        static func usesNowBetterHere(_ label: String, better: String) -> String {
            "Searching with \(label). \(better) runs on this Mac too and finds looser matches — pick it to see its download size."
        }
        static func moving(_ label: String, done: Int, total: Int) -> String {
            total > 0
                ? "Re-reading your memory for \(label) — step \(done) of \(total). Search keeps working meanwhile."
                : "Re-reading your memory for \(label). Search keeps working meanwhile."
        }
        static func movingAfterSleep(_ label: String) -> String {
            "Switching to \(label) waits for Sleep to finish. Search keeps working."
        }
        static let installingGeneric = "Getting it ready…"
        /// Review B1 — picking a version not on this Mac asks first; the size is said before the click.
        static func confirmDownload(_ label: String, bytes: Int) -> String {
            bytes > 0
                ? "\(label) isn't on this Mac yet: a one-time download of about \(Copy.SearchFiles.megabytes(bytes)) that stays on this Mac. Then search switches to it."
                : "\(label) isn't on this Mac yet: a one-time download that stays on this Mac. Then search switches to it."
        }
        static let confirmDownloadButton = "Download"
        static let confirmDownloadHelp = "Downloads it once, then switches search to it."
        static let confirmCancel = "Not now"
        static func installing(_ step: String) -> String { "\(step)…" }
        static func installedChoose(_ label: String) -> String { "\(label) is on this Mac — pick it to switch." }
        static let loadFailed = "Couldn't check how search is set up. Open this page again to retry."

        // MARK: The larger version's sheet (the person's own account)
        static let sheetTitle = "Get the larger version"
        static let sheetWhy = "The larger version is published on Hugging Face under terms you accept with your own account there, so Cicada needs a key from that account to download it once."
        static let sheetTokenUse = "The key is used for that download only and isn't saved. The larger version takes about 2 GB on this Mac."
        static let stepLicense = "1. Accept the terms on its page, signed in to your own account."
        static let openModelPage = "Open its page"
        static let stepToken = "2. Create a read-only key."
        static let createToken = "Create a key"
        static let stepPaste = "3. Paste the key here."
        static let tokenLabel = "Key"
        static let tokenPlaceholder = "hf_…"
        static let install = "Download"
        static let cancel = "Cancel"
        static let installHelp = "Downloads the larger version once, then forgets the key."
        static let installDisabledHelp = "Paste a key that starts with hf_."
    }
}
