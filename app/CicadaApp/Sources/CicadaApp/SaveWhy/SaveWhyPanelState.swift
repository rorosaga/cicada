import Foundation

/// G191 — the panel's behaviour as a value: every tap, key and timer is an `Event`, every consequence an `Effect`.
/// The view and the window only forward events and carry out effects, so the whole interaction is tested here.
///
/// **v3 (owner 2026-10-15: "We should have the option to select various reasons of interest as well as input
/// something in the text bar").** The owner never found v2's multi-select: a tap saved itself after a 2.5 s linger, so
/// the panel was gone before a second tap. Now:
///
/// - **The chips are toggles**, drawn as such (a check that is there or not, in a slot that never moves), and any
///   number can be on.
/// - **The words are always there**: one field under the chips, typed into once the panel is clicked.
/// - **Return or Save confirms.** Nothing closes the panel while the person is choosing: after a tap it waits
///   `SaveWhyPolicy.answerIdle` for the next input (`writingIdle` once words are typed), then keeps what was chosen.
/// - **Leaving keeps what was chosen.** A click elsewhere, Esc, the idle timeout or a newer bookmark closes the panel
///   with the taps and the words as they stand — one tap and leaving is still an answer. With nothing chosen and
///   nothing typed, closing is silent.
/// - **Pending** (`item == nil`): the panel opened when Chrome showed its bookmark bubble, before Chrome wrote the
///   file. The chips are live; the answer is bound to the bookmark once the sync confirms it (`bind`), and is never
///   posted against a guess — the center drops it if no bookmark arrives (`withdrawn`).
/// - **No projects (G191 v4, owner 2026-10-15: "keep options to a minimal").** The panel offers the four basic
///   reasons and the field; a project is never one of its choices.
struct SaveWhyPanelState: Equatable {
    enum Phase: Equatable {
        /// Nothing chosen yet; leaves silently after `SaveWhyPolicy.askTimeout`.
        case asking
        /// Something chosen or typed; waits for Return, Save or more input.
        case answered
        case closed(Outcome)
    }

    enum Outcome: Equatable {
        case answered(SavedWhyAnswer)
        /// Closed with nothing chosen: nothing posted, the bookmark is captured as it always was.
        case dismissed
        /// "Don't ask for this site", with whatever was already chosen (nil when nothing).
        case muted(SavedWhyAnswer?)
        /// A pending panel no bookmark came for (Chrome showed some other bubble): nothing kept.
        case withdrawn
    }

    enum Event: Equatable {
        case tapReason(String)
        case draftChanged(String)
        /// Return in the field, or Save.
        case submit
        /// No input for `answerIdle` / `writingIdle` after something was chosen.
        case idleElapsed
        /// Nothing chosen for `askTimeout`.
        case timeout
        case escape
        case clickOutside
        case dontAskForSite
        /// G191 live: a newer bookmark took the panel's place — closes like leaving, keeping what was chosen.
        case superseded
        /// The pending panel's bookmark never came.
        case withdraw
    }

    enum Effect: Equatable {
        case startTimer(TimeInterval)
        case post(SavedWhyAnswer)
        case mute(String)
        case close
    }

    /// The bookmark asked about; nil while pending (the bubble seen, the file not written yet).
    private(set) var item: FreshBookmark?
    /// The browser the bookmark is being made in (the pending panel's only fact).
    let channel: String
    let order: [String]
    private(set) var phase: Phase = .asking
    private(set) var reasons: Set<String> = []
    private(set) var draft = ""
    let maxText: Int

    init(item: FreshBookmark, order: [String], maxText: Int = 500) {
        self.item = item
        self.channel = item.channel
        self.order = order
        self.maxText = maxText
    }

    /// A pending panel for a bookmark being made in `channel`'s browser.
    init(pendingIn channel: String, order: [String], maxText: Int = 500) {
        self.item = nil
        self.channel = channel
        self.order = order
        self.maxText = maxText
    }

    var isOpen: Bool { if case .closed = phase { return false } else { return true } }
    var isPending: Bool { item == nil }
    /// The person has typed words: nothing replaces the panel while they write.
    var isWriting: Bool { isOpen && !words.isEmpty }

    /// The draft as it would be saved: whitespace folded, capped.
    var words: String { draft.split(whereSeparator: \.isWhitespace).joined(separator: " ") }

    /// What the person has chosen so far, in the panel's order, with their words.
    var selection: SavedWhyAnswer {
        SavedWhyAnswer(reasons: order.filter(reasons.contains), project: nil, text: words.isEmpty ? nil : words)
    }

    func isSelected(reason key: String) -> Bool { reasons.contains(key) }

    /// The effects of opening: the question's own timer.
    static func opening() -> [Effect] { [.startTimer(SaveWhyPolicy.askTimeout)] }

    /// The bookmark arrived (a pending panel) or a newer read named it more exactly: keep every tap and word.
    mutating func bind(_ bookmark: FreshBookmark) {
        guard bookmark.channel == channel || item == nil else { return }
        item = bookmark
    }

    mutating func send(_ event: Event) -> [Effect] {
        guard isOpen else { return [] }
        switch event {
        case .tapReason(let key):
            if reasons.contains(key) { reasons.remove(key) } else { reasons.insert(key) }
            return afterInput()
        case .draftChanged(let text):
            let capped = String(text.prefix(maxText))
            guard capped != draft else { return [] }
            draft = capped
            return afterInput()
        case .submit, .idleElapsed, .escape, .clickOutside, .superseded:
            return finish(selection.isEmpty ? .dismissed : .answered(selection))
        case .timeout:
            // Only the question's own timer: something chosen since runs on the idle timer instead.
            guard selection.isEmpty else { return [] }
            return finish(.dismissed)
        case .withdraw:
            phase = .closed(.withdrawn)
            return [.close]
        case .dontAskForSite:
            guard let host = item?.host else { return [] }   // pending: no site to name yet
            let taps = selection
            return [.mute(host)] + finish(.muted(taps.isEmpty ? nil : taps))
        }
    }

    private mutating func afterInput() -> [Effect] {
        if selection.isEmpty {
            phase = .asking
            return [.startTimer(SaveWhyPolicy.askTimeout)]
        }
        phase = .answered
        return [.startTimer(words.isEmpty ? SaveWhyPolicy.answerIdle : SaveWhyPolicy.writingIdle)]
    }

    private mutating func finish(_ outcome: Outcome) -> [Effect] {
        phase = .closed(outcome)
        switch outcome {
        case .answered(let answer): return [.post(answer), .close]
        case .muted(let answer?): return [.post(answer), .close]
        case .muted(nil), .dismissed, .withdrawn: return [.close]
        }
    }
}
