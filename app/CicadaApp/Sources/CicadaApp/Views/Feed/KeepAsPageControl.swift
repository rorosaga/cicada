import Observation
import SwiftUI

/// G246 (ruling 81, plan Track K) — the one control on a saved post drawn as a row: "Keep as a page", and, once the
/// person's own click holds the page and nothing else does, "Back to a row". It is reusable: the Feed's detail wears it
/// now, and a card's menu or a stream row takes `KeepAsPageControl(url:)` the same way.
///
/// The control asks the backend what to offer (`GET /sources/keep-as-page`) and draws nothing for any answer but a row
/// or a kept post, so while the posts-as-rows switch is off (`saved_posts.HIDE_POSTS`) it never appears. The app holds
/// no rule about which saves are posts. Pressing it posts the click, which the backend stamps and commits as the person;
/// the page then reaches the graph at its next read (`Store.refresh([.graph, …])` asks for it now).
///
/// Applies DR-40 (a neutral button, compact), DR-41 (disabled keeps its label while the call is out), DR-60 (a click,
/// no keyboard action to animate), DR-2 (the failure line is `textTertiary`), DR-34 (no padding of its own on a row).
@MainActor
@Observable
final class KeepAsPageModel {
    typealias Fetch = (String) async throws -> KeepAsPageState
    typealias Send = (String, Bool) async throws -> KeepAsPageReply

    private(set) var state: KeepAsPageState?
    private(set) var working = false
    /// The words for a click that did not land; cleared by the next press.
    private(set) var failure: String?
    /// What the last click did, in words ("Kept as a page").
    private(set) var done: String?

    private let fetch: Fetch
    private let send: Send

    init(fetch: @escaping Fetch = { try await APIClient.shared.keepAsPageState(url: $0) },
         send: @escaping Send = { try await APIClient.shared.keepAsPage(url: $0, kept: $1) }) {
        self.fetch = fetch
        self.send = send
    }

    var offer: KeepAsPageOffer? { KeepAsPage.offer(state) }

    /// Read what this link may offer. A failed read offers nothing: a control must never appear on a guess.
    func load(url: String) async {
        state = nil
        failure = nil
        done = nil
        state = try? await fetch(url)
    }

    /// Press the offered control. Returns the reply when the backend changed or confirmed it (the caller refreshes the
    /// graph), nil when there was nothing to press, a call is already out, or it failed (`failure` says why).
    @discardableResult
    func press(url: String) async -> KeepAsPageReply? {
        guard let offer, !working else { return nil }
        working = true
        failure = nil
        done = nil
        defer { working = false }
        do {
            let reply = try await send(url, offer.asksToKeep)
            state = reply.state
            if reply.status != "unchanged" { done = offer.done }
            return reply
        } catch {
            failure = KeepAsPage.failureLine(error)
            return nil
        }
    }
}

struct KeepAsPageControl: View {
    let url: String
    var topPadding: CGFloat = CicadaTheme.scaled(16)

    @Environment(Store.self) private var store
    @State private var model = KeepAsPageModel()

    var body: some View {
        Group {
            if model.offer != nil || model.failure != nil || model.done != nil {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let offer = model.offer {
                        NeutralButton(title: offer.title, size: .compact, isDisabled: model.working, help: offer.help) {
                            Task { await press() }
                        }
                    }
                    if let line = model.failure ?? model.done {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityLabel(line)
                    }
                }
                .padding(.top, topPadding)
            }
        }
        .task(id: url) { await model.load(url: url) }
    }

    private func press() async {
        guard await model.press(url: url) != nil else { return }
        // The kept post is a node at the next read of the graph, and its row's card says "has a page".
        await store.refresh([.graph, .sources])
    }
}
