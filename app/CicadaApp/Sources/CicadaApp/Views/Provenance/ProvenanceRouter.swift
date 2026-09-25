import Foundation
import Observation

/// Where the Reader should open, and what it should land on (design §1.4,
/// §4.4). Every "where did this come from" affordance — an evidence chip, a
/// provenance row, an inbox cause, an Ask citation, and later a palette hit
/// (P6) — builds one of these and hands it to `ProvenanceRouter.open(_:)`.
///
/// `.conversation(id)` from the design is deliberately absent: the Reader
/// reads `/episodes/{id}/text`, and a conversation id cannot be turned into
/// an episode id without a server field `ConversationSummary` does not carry
/// (plan R-PU5). A caller that knows the conversation also knows one of its
/// episodes, or does not offer the button.
struct ReaderTarget: Hashable, Identifiable {
    enum Focus: Hashable {
        /// Open at the top.
        case none
        /// A stored span. `hash` rides along so the server can say `grown` or
        /// `stale` (A7); `derived` marks a name match found at read — it lands
        /// and bolds, never washes, and never reads "You said" (§4.9).
        case span(start: Int, end: Int, hash: String?, derived: Bool)
        /// Let the server find the entity's name (`?focus=`): the legacy-claim
        /// path, always derived (R-PB9).
        case mention(entityId: String)
        /// A `reasoning` entry: the contributor inferred it here, and no
        /// sentence says so. Opens at the top under that banner.
        case inferred
        /// A best quote whose conversation changed since (R-PB2: a stale span
        /// travels without offsets). Opens at the top under the stale banner.
        case stale
    }

    let episode: String
    let focus: Focus
    /// The entity whose beliefs brought the person here. The navigator
    /// (P4) steps through the spans this entity's claims cite.
    let subjectId: String?
    /// Header fields a caller already holds, shown while the text loads
    /// (§4.4 "Loading: the header from the target's known fields").
    let knownTitle: String?
    let knownHarness: String?

    init(episode: String, focus: Focus = .none, subjectId: String? = nil,
         knownTitle: String? = nil, knownHarness: String? = nil) {
        self.episode = episode
        self.focus = focus
        self.subjectId = subjectId
        self.knownTitle = knownTitle
        self.knownHarness = knownHarness
    }

    var id: String { "\(episode)|\(focus)|\(subjectId ?? "")" }

    /// What `/episodes/{id}/text` is asked for. `.inferred`/`.stale` ask for
    /// nothing: there is no offset to judge.
    var query: ReaderFocusQuery {
        switch focus {
        case let .span(start, end, hash, _): .span(start: start, end: end, hash: hash)
        case let .mention(entityId): .mention(entityId: entityId)
        case .none, .inferred, .stale: .none
        }
    }

    /// One stored evidence entry → where to open. A span lands on its words;
    /// a `reasoning` entry that still names its document opens that document
    /// under the "inferred" banner; anything else has nowhere to go.
    static func evidence(_ ev: Evidence, subjectId: String?, knownTitle: String? = nil,
                         knownHarness: String? = nil) -> ReaderTarget? {
        guard !ev.episode.isEmpty else { return nil }
        if ev.isSpan {
            return ReaderTarget(episode: ev.episode,
                                focus: .span(start: ev.start, end: ev.end, hash: ev.hash, derived: false),
                                subjectId: subjectId, knownTitle: knownTitle, knownHarness: knownHarness)
        }
        return ReaderTarget(episode: ev.episode, focus: .inferred, subjectId: subjectId,
                            knownTitle: knownTitle, knownHarness: knownHarness)
    }

    /// A provenance row's best quote (R-PB8) → where to open. Asserted and
    /// grown quotes land exactly; a derived one lands bold; a stale one opens
    /// at the top under the stale banner, because its offsets were withheld.
    static func best(_ best: ProvenanceSpan, subjectId: String?, knownTitle: String? = nil,
                     knownHarness: String? = nil) -> ReaderTarget {
        let focus: Focus
        if best.stale {
            focus = .stale
        } else if let start = best.start, let end = best.end, end > start {
            focus = .span(start: start, end: end, hash: best.derived ? nil : best.hash, derived: best.derived)
        } else {
            focus = .none
        }
        return ReaderTarget(episode: best.episode, focus: focus, subjectId: subjectId,
                            knownTitle: knownTitle, knownHarness: knownHarness)
    }
}

/// The Reader's navigation (design §1.4): a stack of targets, one Reader column.
/// Injected into the main window's environment (`CicadaApp`) and read as an
/// OPTIONAL environment value by every chip, so a view hosted anywhere else
/// (a preview, a test) renders its chip without a click-through rather than
/// trapping on a missing environment object.
@Observable
@MainActor
final class ProvenanceRouter {
    /// A reading trail, not a history: capped so an afternoon of clicking
    /// never grows it without bound.
    static let maxDepth = 20

    private(set) var stack: [ReaderTarget] = []
    /// Read by the Reader column's host; the stack is kept so the closing
    /// animation never shows an empty Reader, and the next `open` from closed
    /// starts a fresh one.
    var isPresented = false
    /// Bumped on every `open`, including re-opening the target already on
    /// top — the one signal a presenter (the Ask sheet, T6) can watch to get
    /// out of the Reader's way.
    private(set) var revision = 0

    var current: ReaderTarget? { stack.last }
    var canGoBack: Bool { stack.count > 1 }

    func open(_ target: ReaderTarget) {
        if !isPresented { stack = [] }
        if stack.last != target { stack.append(target) }
        if stack.count > Self.maxDepth { stack.removeFirst(stack.count - Self.maxDepth) }
        isPresented = true
        revision &+= 1
    }

    /// DR-29 / R-DI9 — the next question cites the conversation already open: re-land on its span in
    /// place. The top target is replaced, not pushed — Back is for moving between documents, and
    /// answering five questions beside one conversation must not build five Back steps. Anything
    /// else is an ordinary `open`.
    func refocus(_ target: ReaderTarget) {
        guard isPresented, let top = stack.last, top.episode == target.episode else {
            open(target)
            return
        }
        stack[stack.count - 1] = target
        revision &+= 1
    }

    func back() {
        guard canGoBack else { return }
        stack.removeLast()
    }

    func close() { isPresented = false }
}
