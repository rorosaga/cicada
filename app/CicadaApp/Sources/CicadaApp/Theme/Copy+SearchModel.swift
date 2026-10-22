import Foundation

/// G182 phase 3, reworded for Search & files (owner, 2026-10-14) — the words `SearchModelLogic` uses for a search
/// version's state. The *Search version* picker and the larger version's account sheet left the app (settings
/// defaults, owner 2026-10-22); `cicada index` does both on the command line. The page's two consent rows are
/// `Copy.SearchFiles`. Provider-neutral (owner, 2026-09-30): the step is described, never a provider doing it;
/// Hugging Face is named only where the person must use their own account there. A version's own label ("Built in",
/// "Sharper", "Larger") comes from the backend's catalog, the person's choice.
extension Copy {
    enum SearchModel {
        // MARK: A search version's state, in words
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
        static func installing(_ step: String) -> String { "\(step)…" }
        static func installedChoose(_ label: String) -> String { "\(label) is on this Mac — pick it to switch." }
    }
}
