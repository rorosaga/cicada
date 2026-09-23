import SwiftUI

/// Settings → Memory (G139): the derived search index and the link backfill,
/// both user-started and both refused with a plain sentence while Sleep runs.
/// Rebuilding the index costs CPU, never a fact (TODO ruling 3), which is why
/// it can sit behind one button with no confirmation.
///
/// "Look for duplicates" is deliberately absent (R-O17): the dedup endpoint
/// blocks the event loop, its dry run never reaches the Inbox, and its live
/// run leaves uncommitted merges for the next `git add -A` writer (the G85
/// smear). `CicadaPagesTests.testNoPageCallsTheDedupSweep` holds that line.
struct MemoryView: View {
    @State private var index: SearchIndexStatus?
    @State private var indexNote: String?
    @State private var linksNote: String?
    @State private var busy = false

    var body: some View {
        SettingsPage(section: .memory) {
            SettingsGroupCard {
                SettingsRow(.searchIndex, title: Copy.searchIndexTitle, detail: indexNote ?? MemoryMaintenanceText.index(index)) {
                    Button(Copy.rebuildNow) {
                        run {
                            index = try await APIClient.shared.rebuildSearchIndex()
                            indexNote = nil
                        } onError: { indexNote = $0 }
                    }
                    .disabled(busy)
                }
                SettingsDivider()
                SettingsRow(.enrichLinks, title: Copy.enrichLinksTitle, detail: linksNote ?? Copy.enrichLinksDetail) {
                    Button(Copy.fetchNow) {
                        run {
                            linksNote = MemoryMaintenanceText.links(try await APIClient.shared.enrichLinksNow())
                        } onError: { linksNote = $0 }
                    }
                    .disabled(busy)
                }
            }
        }
        .task { index = try? await APIClient.shared.fetchSearchIndexStatus() }
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
                onError(message.localizedCaseInsensitiveContains("sleep") ? Copy.sleepIsRunning : Copy.alreadyRunning)
            } catch {
                onError(AddSourceSheet.friendlyError(error))
            }
        }
    }
}
