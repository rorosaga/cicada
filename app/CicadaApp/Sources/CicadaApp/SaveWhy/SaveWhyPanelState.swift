import Foundation

/// G191 — the panel's behaviour as a value: every tap, key and timer is an `Event`, every consequence an `Effect`.
/// The view and the window only forward events and carry out effects, so the whole interaction is tested here.
///
/// **Multi-select, still one tap.** A tap selects an answer and starts a short linger (`SaveWhyPolicy.linger`); a
/// second tap within it adds (or removes) another, and the linger restarts; when it runs out, the answer is saved and
/// the panel leaves. So the common case is one tap and no confirm button, and the case the owner described in G191 —
/// a site saved for its design *and* its product — is one more tap, not a false choice between them.
///
/// **A tap is an answer.** Once something is tapped, closing the panel early (Esc, a click elsewhere, a timeout) saves
/// what was tapped instead of throwing it away; with nothing tapped, closing is silent and nothing is posted. Words
/// typed under "Something else…" are sent only with Return — an unsent draft is dropped, the taps kept.
struct SaveWhyPanelState: Equatable {
    enum Phase: Equatable {
        /// The question, nothing chosen yet; leaves silently after `SaveWhyPolicy.askTimeout`.
        case asking
        /// Something chosen; saves after `SaveWhyPolicy.linger` unless another tap comes.
        case answered
        /// "Something else…" is open; Return sends.
        case writing
        case closed(Outcome)
    }

    enum Outcome: Equatable {
        case answered(SavedWhyAnswer)
        /// Closed with nothing chosen: nothing posted, the bookmark is captured as it always was.
        case dismissed
        /// "Don't ask for this site", with whatever was already tapped (nil when nothing).
        case muted(SavedWhyAnswer?)
    }

    enum Event: Equatable {
        case tapReason(String)
        case tapProject(String)
        case tapOther
        case draftChanged(String)
        case submitText
        case lingerElapsed
        case timeout
        case escape
        case clickOutside
        case dontAskForSite
        /// G191 live: a newer bookmark took the panel's place — closes like a timeout, keeping any tap.
        case superseded
    }

    enum Effect: Equatable {
        case startTimer(TimeInterval)
        case focusText
        case post(SavedWhyAnswer)
        case mute(String)
        case close
    }

    let item: FreshBookmark
    let order: [String]
    private(set) var phase: Phase = .asking
    private(set) var reasons: Set<String> = []
    private(set) var project: String?
    private(set) var draft = ""
    let maxText: Int

    init(item: FreshBookmark, order: [String], maxText: Int = 500) {
        self.item = item
        self.order = order
        self.maxText = maxText
    }

    var isOpen: Bool { if case .closed = phase { return false } else { return true } }

    /// What the person has chosen so far, in the panel's order (the draft only once sent).
    var selection: SavedWhyAnswer {
        SavedWhyAnswer(reasons: order.filter(reasons.contains), project: project, text: nil)
    }

    func isSelected(reason key: String) -> Bool { reasons.contains(key) }
    func isSelected(project id: String) -> Bool { project == id }

    /// The effects of opening: the question's own timer.
    static func opening() -> [Effect] { [.startTimer(SaveWhyPolicy.askTimeout)] }

    mutating func send(_ event: Event) -> [Effect] {
        guard isOpen else { return [] }
        switch event {
        case .tapReason(let key):
            if reasons.contains(key) { reasons.remove(key) } else { reasons.insert(key) }
            return afterTap()
        case .tapProject(let id):
            project = project == id ? nil : id
            return afterTap()
        case .tapOther:
            phase = .writing
            return [.startTimer(SaveWhyPolicy.writingTimeout), .focusText]
        case .draftChanged(let text):
            draft = String(text.prefix(maxText))
            return []
        case .submitText:
            let words = draft.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            var answer = selection
            answer.text = words.isEmpty ? nil : words
            return finish(answer.isEmpty ? .dismissed : .answered(answer))
        case .lingerElapsed:
            guard phase == .answered else { return [] }
            return finish(.answered(selection))
        case .timeout, .escape, .clickOutside, .superseded:
            return finish(selection.isEmpty ? .dismissed : .answered(selection))
        case .dontAskForSite:
            let taps = selection
            var effects: [Effect] = item.host.map { [.mute($0)] } ?? []
            effects += finish(.muted(taps.isEmpty ? nil : taps))
            return effects
        }
    }

    private mutating func afterTap() -> [Effect] {
        if phase == .writing { return [] }   // still writing: Return sends the taps with the words
        if selection.isEmpty {
            phase = .asking
            return [.startTimer(SaveWhyPolicy.askTimeout)]
        }
        phase = .answered
        return [.startTimer(SaveWhyPolicy.linger)]
    }

    private mutating func finish(_ outcome: Outcome) -> [Effect] {
        phase = .closed(outcome)
        switch outcome {
        case .answered(let answer): return [.post(answer), .close]
        case .muted(let answer?): return [.post(answer), .close]
        case .muted(nil), .dismissed: return [.close]
        }
    }
}
