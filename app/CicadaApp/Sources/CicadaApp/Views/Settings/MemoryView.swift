import SwiftUI

/// Settings → Memory (G139): the link backfill, user-started and refused with a plain sentence while Sleep runs, and
/// G147's *How things fade* (`FadePaceCard`) — suggestions from the person's own decay answers, applied only on Apply.
///
/// Search & files (owner, 2026-10-14) took the search index and the search version: how Cicada *finds* things now
/// lives on `SearchFilesView`, and Memory keeps how it tidies what it knows.
///
/// "Look for duplicates" is deliberately absent (R-O17): the dedup endpoint
/// blocks the event loop, its dry run never reaches the Inbox, and its live
/// run leaves uncommitted merges for the next `git add -A` writer (the G85
/// smear). `CicadaPagesTests.testNoPageCallsTheDedupSweep` holds that line.
struct MemoryView: View {
    @State private var linksNote: String?
    @State private var busy = false

    var body: some View {
        SettingsPage(section: .memory) {
            SettingsGroupCard {
                SettingsRow(.enrichLinks, title: Copy.enrichLinksTitle, detail: linksNote ?? Copy.enrichLinksDetail) {
                    NeutralButton(title: Copy.fetchNow, size: .compact, isDisabled: busy) {
                        run {
                            linksNote = MemoryMaintenanceText.links(try await APIClient.shared.enrichLinksNow())
                        } onError: { linksNote = $0 }
                    }
                }
            }
            FadePaceCard()
        }
    }

    /// `work` is `@MainActor` because it assigns this view's `@State` after an
    /// `await` — a plain async closure could resume off the main thread.
    /// A 409 is either Sleep (which writes the same files) or another run of
    /// the same job; both backends say which in their `detail`.
    private func run(_ work: @escaping @MainActor () async throws -> Void,
                     onError: @escaping @MainActor (String) -> Void) {
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                try await work()
            } catch APIError.httpError(409, let message) {
                onError(SleepRefusal.matches(APIError.httpError(409, message)) ? Copy.sleepIsRunning : Copy.alreadyRunning)
            } catch {
                onError(AddSourceSheet.friendlyError(error))
            }
        }
    }
}
