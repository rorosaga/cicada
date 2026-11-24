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

    /// A row of a list already knows what it may offer (`ChannelItem.keep`, from the same predicate): draw it with no call.
    /// Touches nothing else, so a line that says what the last click did stays until the next press.
    func seed(_ state: KeepAsPageState) {
        self.state = state
    }

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
    /// The saved link, or — for a row of a list, which holds no link — the row's own page id.
    let url: String
    var topPadding: CGFloat = CicadaTheme.scaled(16)
    /// A row of a list: what the row was told to offer (`row` or `kept`), so the control reads nothing of its own and
    /// asks the backend by the page id. Nil is the Feed's own: it reads what its link may offer.
    var rowWord: String?
    /// A quiet text button (DR-40's `TextButton`) for a control repeated down a list; the Feed's detail keeps the neutral one.
    var inline = false

    @Environment(Store.self) private var store: Store?
    @State private var model: KeepAsPageModel

    init(url: String, topPadding: CGFloat = CicadaTheme.scaled(16)) {
        self.url = url
        self.topPadding = topPadding
        self.rowWord = nil
        self.inline = false
        _model = State(initialValue: KeepAsPageModel())
    }

    /// The control on one row of a list (`ChannelItem.keep` is its word, `ChannelItem.id` the page).
    init(row page: String, word: String?) {
        self.url = page
        self.topPadding = 0
        self.rowWord = word
        self.inline = true
        _model = State(initialValue: KeepAsPageModel(
            fetch: { _ in .none },
            send: { page, kept in try await APIClient.shared.keepAsPage(entity: page, kept: kept) }))
    }

    var body: some View {
        Group {
            if model.offer != nil || model.failure != nil || model.done != nil {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let offer = model.offer {
                        if inline {
                            TextButton(title: offer.title, help: offer.help, inline: true, flushLeading: true) {
                                Task { await press() }
                            }
                            .disabled(model.working)
                        } else {
                            NeutralButton(title: offer.title, size: .compact, isDisabled: model.working, help: offer.help) {
                                Task { await press() }
                            }
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
        .task(id: "\(url)|\(rowWord ?? "")") {
            if inline { model.seed(KeepAsPage.seeded(rowWord, page: url)) } else { await model.load(url: url) }
        }
    }

    private func press() async {
        guard await model.press(url: url) != nil else { return }
        // The kept post is a node at the next read of the graph, and its row's card says "has a page".
        await store?.refresh([.graph, .sources])
    }
}
