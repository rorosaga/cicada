import Foundation

/// G182 phase 3 — Settings → Memory → Search model and its install sheet. Provider-neutral
/// (owner, 2026-09-30): the step is described, never a provider doing it; Hugging Face is
/// named only where the person must use their own account there. A model's own label
/// ("Small", "Larger") comes from the backend's catalog, the person's choice.
extension Copy {
    enum SearchModel {
        // MARK: The row
        static let title = "Search model"
        static let pickerHelp = "How search matches what you mean, not only the words you type."
        static let sleepRunningHelp = "Sleep is running — change the search model when it finishes."
        static let anotherModel = "another model"
        static let usesOther = "Searching with another model set up on this Mac."
        static func builtWithMissing(_ label: String) -> String {
            "This memory was built with the \(label) model, which isn't on this Mac yet — search uses words until you install it."
        }
        static func usesNow(_ label: String, detail: String) -> String {
            detail.isEmpty ? "Searching with the \(label) model." : "Searching with the \(label) model. \(detail)"
        }
        static func switchesAtNextSleep(_ label: String) -> String {
            "Search switches to \(label) at the next Sleep, which re-reads this memory once."
        }
        static let installingGeneric = "Installing the larger model…"
        static func installing(_ step: String) -> String { "\(step)…" }
        static func installedChoose(_ label: String) -> String { "\(label) is ready on this Mac — choose it to switch." }
        static let loadFailed = "Couldn't read the search model — open this page again to retry."

        // MARK: The install sheet
        static let sheetTitle = "Install the larger search model"
        static let sheetWhy = "The larger model is published under a license you accept on Hugging Face, so Cicada needs your own read-access token to download it once."
        static let sheetTokenUse = "The token is used for that download only and isn't saved. The model takes about 2 GB on this Mac."
        static let stepLicense = "1. Accept the license on the model's page, signed in to your own account."
        static let openModelPage = "Open the model's page"
        static let stepToken = "2. Create a token with read access."
        static let createToken = "Create a token"
        static let stepPaste = "3. Paste the token here."
        static let tokenLabel = "Access token"
        static let tokenPlaceholder = "hf_…"
        static let install = "Install"
        static let cancel = "Cancel"
        static let installHelp = "Downloads the larger model once, then forgets the token."
        static let installDisabledHelp = "Paste a token that starts with hf_."
    }
}
