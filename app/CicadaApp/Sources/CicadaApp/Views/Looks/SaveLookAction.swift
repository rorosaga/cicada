import SwiftUI

/// Looks v2 (owner, 2026-10-15) — "Save its look" on a saved link: one click queues a design visit for it in the
/// explore queue (`POST /explore/look`; ruling 25's starter is the person's click). The person's own agent
/// (site-explore, browser-harness) captures the page, its computed type and colours, and the landing picture becomes a
/// Look. Cicada never opens a browser: the answer carries the hand-off prompt, which is copied for the person to give
/// their agent, as "Ask an agent" does for reading (`FeedReadSection`).
enum SaveLook {
    enum Outcome: Equatable {
        case queued(prompt: String)
        case failed(String)
    }

    /// The click's one call; the server's own sentence on a refusal it explains (409 reading off / demo, 422 not
    /// explorable), else a plain one.
    static func run(mediaEntityId: String, url: String, api: any ExploreAPI = APIClient.shared) async -> Outcome {
        do {
            let answer = try await api.saveLook(mediaEntityId: mediaEntityId, url: url)
            return .queued(prompt: answer.prompt)
        } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
            return .failed(ProjectWriteFailure.detail(body) ?? Copy.Looks.saveLookFailed)
        } catch {
            return .failed(Copy.Looks.saveLookFailed)
        }
    }

    /// Whether a saved item can be asked for its look: a web page (not a video or a paper; the server has the last
    /// word on what is explorable).
    static func offers(_ item: MediaFeedItem) -> Bool {
        let kind = FeedKind.of(item)
        guard kind == .link || kind == .bookmark, let scheme = URL(string: item.url)?.scheme?.lowercased() else {
            return false
        }
        return scheme == "http" || scheme == "https"
    }

    /// Run it and tell the person: the prompt copied and a toast, or the reason it couldn't be queued.
    @MainActor
    static func perform(mediaEntityId: String, url: String, store: Store) async {
        switch await run(mediaEntityId: mediaEntityId, url: url) {
        case .queued(let prompt):
            AppPasteboard.copy(prompt)
            store.toast = Copy.Looks.saveLookQueued
        case .failed(let why):
            store.toast = why
        }
    }
}

/// The button in a saved item's detail column (DR-40: neutral, compact; DR-41: disabled while it runs).
struct SaveLookButton: View {
    let mediaEntityId: String
    let url: String
    @Environment(Store.self) private var store
    @State private var busy = false

    var body: some View {
        NeutralButton(title: Copy.Looks.saveLook, size: .compact, isDisabled: busy, help: Copy.Looks.saveLookHelp) {
            busy = true
            Task {
                await SaveLook.perform(mediaEntityId: mediaEntityId, url: url, store: store)
                busy = false
            }
        }
    }
}
