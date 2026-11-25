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
/// - **Return or Save confirms.** Nothing closes the panel while the person is choosing.
/// - **Leaving keeps what was chosen.** A click elsewhere, Esc or a newer bookmark closes the panel with the taps and
///   the words as they stand — one tap and leaving is still an answer. With nothing chosen and nothing typed, closing
///   is silent.
/// - **A click somewhere else never closes it at once (owner 2026-11-25: "the notification doesn't go away on the
///   first click, but rather … a timer of sorts that has a bar filling up at the bottom from left to right"; this
///   amends 2026-10-19's "unless I click anywhere else on the screen").** An untouched question leaves only when its
///   bar has filled (`SaveWhyPolicy.askTimeout`, `countsDown`); a click elsewhere changes nothing.
/// - **Touched, the bar's timer stops ("when clicked to type something the timer stops").** A tap, a word, a click
///   into the field (`engage` — dictation types nothing until it is done) or a click anywhere on the panel (`touch`)
///   stops it, and the bar goes. From then on, each time the person clicks somewhere else a quiet wait starts
///   (`SaveWhyPolicy.awayCooldown`, no bar, `away`), after which the panel leaves keeping what was chosen; a click
///   back on the panel ends the wait ("the cooldown resets every time I click on it again"), and the next click
///   away starts it from the beginning. Save, Return, Esc and a newer bookmark still close it at once.
/// - **A bookmark already saved is edited, not asked again (owner 2026-10-19: "It should just put the same Cicada
///   prompt, but with the text already filled in or the selection already made").** `init(editing:)` opens with the
///   newest answer's taps and words; leaving with a change is an `edit` of that answer, leaving unchanged writes
///   nothing.
/// - **Pending** (`item == nil`): the panel opened when Chrome showed its bookmark bubble, before Chrome wrote the
///   file. The chips are live; the answer is bound to the bookmark once the sync confirms it (`bind`), and is never
///   posted against a guess — the center drops it if no bookmark arrives (`withdrawn`).
/// - **No projects (G191 v4, owner 2026-10-15: "keep options to a minimal").** The panel offers the four basic
///   reasons and the field; a project is never one of its choices.
struct SaveWhyPanelState: Equatable {
    enum Phase: Equatable {
        /// Nothing chosen yet; an untouched question leaves silently after `SaveWhyPolicy.askTimeout`.
        case asking
        /// Something chosen or typed; waits for the person.
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
        /// A saved answer changed (`at` names it).
        case edited(SavedWhyAnswer, at: String)
        /// An answer already saved, left as it was: nothing written.
        case unchanged
    }

    enum Event: Equatable {
        case tapReason(String)
        case draftChanged(String)
        /// The person clicked into the field: they are about to write or dictate (owner 2026-10-19).
        case engage
        /// Return in the field, or Save.
        case submit
        /// The panel's timer ran out: the untouched question's (`askTimeout`), or the wait after the person clicked
        /// away from a panel they had touched (`awayCooldown`).
        case timeout
        case escape
        /// A click somewhere else. Never closes the panel itself: it starts the wait when the panel was touched.
        case clickOutside
        /// A click anywhere on the panel: the person is in it, so no timer runs.
        case touch
        case dontAskForSite
        /// G191 live: a newer bookmark took the panel's place — closes like leaving, keeping what was chosen.
        case superseded
        /// The pending panel's bookmark never came.
        case withdraw
    }

    enum Effect: Equatable {
        case startTimer(TimeInterval)
        /// The person touched the panel: no timer closes it any more.
        case stopTimer
        case post(SavedWhyAnswer)
        /// Change the answer said at `at` (an already-saved bookmark's).
        case edit(SavedWhyAnswer, at: String)
        case mute(String)
        case close
    }

    /// An answer already on the record, opened for editing.
    struct Editing: Equatable {
        /// When it was said: the answer's own key on the backend (`PUT /sources/saved-why`).
        let at: String
        let original: SavedWhyAnswer
    }

    /// The bookmark asked about; nil while pending (the bubble seen, the file not written yet).
    private(set) var item: FreshBookmark?
    /// The browser the bookmark is being made in (the pending panel's only fact).
    let channel: String
    /// Every reason a tap is held for, in the order an answer lists them: the fixed row, then the bank the panel
    /// suggests from (G191 v7).
    private(set) var order: [String]
    private(set) var phase: Phase = .asking
    private(set) var reasons: Set<String> = []
    private(set) var draft = ""
    let maxText: Int
    /// The person has tapped, typed or clicked on the panel: the bar's timer no longer runs.
    private(set) var engaged = false
    /// They touched the panel and then clicked somewhere else: the quiet wait is running.
    private(set) var away = false
    /// They clicked into the field (and may be dictating, with no words yet).
    private(set) var inField = false
    /// Set when the panel edits an answer already saved.
    private(set) var editing: Editing?
    /// What an edited answer holds that the panel cannot show (a retired reason, a project): kept through the edit.
    private(set) var keptReasons: [String] = []
    private(set) var keptProject: String?

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

    /// The panel for a bookmark already saved, filled in with its answer said at `at` (nil `answer`/`at`: saved, never
    /// answered — the panel asks as usual and posts a first answer for that save).
    init(editing item: FreshBookmark, answer: SavedWhyAnswer?, at: String?, order: [String], maxText: Int = 500) {
        self.init(item: item, order: order, maxText: maxText)
        guard let answer, let at, !answer.isEmpty else { return }
        adopt(answer, at: at)
    }

    /// Fill the panel with a saved answer (it becomes an edit of it). A tap made before it arrived stays beside the
    /// saved ones; words typed before it are kept over the saved words — nothing the person did is undone.
    mutating func adopt(_ answer: SavedWhyAnswer, at: String) {
        editing = Editing(at: at, original: answer)
        keptReasons = answer.reasons.filter { !order.contains($0) }
        keptProject = answer.project
        reasons.formUnion(answer.reasons.filter(order.contains))
        if words.isEmpty { draft = String((answer.text ?? "").prefix(maxText)) }
        phase = selection.isEmpty ? .asking : .answered
    }

    var isOpen: Bool { if case .closed = phase { return false } else { return true } }
    /// The untouched question's timer is running: the panel shows its bar.
    var countsDown: Bool { isOpen && !engaged }
    var isPending: Bool { item == nil }
    var isEditing: Bool { editing != nil }
    /// The person is writing — typed words, or the field clicked into (dictation types nothing until it is done):
    /// nothing replaces the panel while they write.
    var isWriting: Bool { isOpen && (inField || !words.isEmpty) }

    /// The draft as it would be saved: whitespace folded, capped.
    var words: String { draft.split(whereSeparator: \.isWhitespace).joined(separator: " ") }

    /// What the person has chosen so far, in the panel's order, with their words (and, editing, what the saved answer
    /// held that the panel does not show).
    var selection: SavedWhyAnswer {
        SavedWhyAnswer(reasons: order.filter(reasons.contains) + keptReasons, project: keptProject,
                       text: words.isEmpty ? nil : words)
    }

    func isSelected(reason key: String) -> Bool { reasons.contains(key) }

    /// The effects of opening: the question's own timer.
    static func opening() -> [Effect] { [.startTimer(SaveWhyPolicy.askTimeout)] }

    /// G191 v7 — reasons the panel may now suggest (the bank arrived after it opened): taps on them are held too. A
    /// reason an edited answer kept unseen becomes a shown one when it is offered, so it is never counted twice.
    mutating func allow(_ keys: [String]) {
        let added = keys.filter { !order.contains($0) }
        guard !added.isEmpty else { return }
        order += added
        let shown = keptReasons.filter(added.contains)
        keptReasons.removeAll(where: added.contains)
        reasons.formUnion(shown)
    }

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
        case .engage:
            inField = true
            return afterInput()
        case .touch:
            return present()
        case .clickOutside:
            // Untouched: the bar decides. Touched: the quiet wait starts, once per leaving (a second click elsewhere
            // does not push it back, or working in the page would keep the panel for ever).
            guard engaged, !away else { return [] }
            away = true
            inField = false
            return [.startTimer(SaveWhyPolicy.awayCooldown)]
        case .submit, .escape, .superseded:
            return finish(leaving())
        case .timeout:
            // The untouched question's bar filled, or the person stayed away for the whole wait. While they are in
            // the panel no timer closes it (owner 2026-10-19).
            guard !engaged || away else { return [] }
            return finish(leaving())
        case .withdraw:
            phase = .closed(.withdrawn)
            return [.close]
        case .dontAskForSite:
            guard let host = item?.host else { return [] }   // pending: no site to name yet
            switch leaving() {
            case .answered(let answer):
                phase = .closed(.muted(answer))
                return [.mute(host), .post(answer), .close]
            case .edited(let answer, let at):
                phase = .closed(.muted(answer))
                return [.mute(host), .edit(answer, at: at), .close]
            default:
                phase = .closed(.muted(nil))
                return [.mute(host), .close]
            }
        }
    }

    /// What leaving now keeps: the answer, an edit of the saved one, or nothing.
    private func leaving() -> Outcome {
        let answer = selection
        if let editing {
            // An emptied answer is never written as a deletion: it stays as it was.
            return answer.isEmpty || answer == editing.original ? .unchanged : .edited(answer, at: editing.at)
        }
        return answer.isEmpty ? .dismissed : .answered(answer)
    }

    private mutating func afterInput() -> [Effect] {
        phase = selection.isEmpty ? .asking : .answered
        return present()
    }

    /// The person is in the panel: whichever timer was running stops (the bar's on the first touch, the quiet wait
    /// when they come back).
    private mutating func present() -> [Effect] {
        guard !engaged || away else { return [] }
        engaged = true
        away = false
        return [.stopTimer]
    }

    private mutating func finish(_ outcome: Outcome) -> [Effect] {
        phase = .closed(outcome)
        switch outcome {
        case .answered(let answer): return [.post(answer), .close]
        case .muted(let answer?): return [.post(answer), .close]
        case .edited(let answer, let at): return [.edit(answer, at: at), .close]
        case .muted(nil), .dismissed, .withdrawn, .unchanged: return [.close]
        }
    }
}
