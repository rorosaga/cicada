import Foundation
import Observation

/// Ruling 48 (8) — *Catch me up* is a conversation, not an interrogation (owner 2026-10-28: "a conversation where the
/// questions themselves can change and more questions can be answered there in the moment as follow ups, same as a
/// human conversation").
///
/// One session = one open chat on Home. Cicada asks the questions on the pages the person uses most first (the inbox's
/// own order), one at a time, in plain words with their reason. The person answers with a tap — the inbox's own
/// resolution, held for the same Undo window (DR-42, `InboxViewModel.answer`) — or in their own words. Their words go
/// to `POST /inbox/catchup/turn`, one turn on their chosen engine (Ask's path), which answers like a person would: a
/// follow-up, the question in other words, or a move to a related question it was offered. A reading grounded in their
/// words is applied through the same hold; a question about who someone is is never applied from a reading, only
/// offered as a one-tap confirmation (ruling 41). With no engine to answer, the chat takes taps (and the person's own
/// words as a free answer, where the question takes one), and says so.
///
/// The chat itself is kept as one episode per session (`POST /inbox/catchup/record`, after each thing the person
/// says), so Sleep reads what they said in passing like any conversation.
@Observable
@MainActor
final class CatchupSession {
    /// The worm's face (`WormFace`): what it is doing, never an animation a key starts (DR-60).
    enum Mood: Equatable { case asking, listening, thinking, pleased, idle }

    typealias Turn = (_ itemId: String, _ message: String, _ history: [CatchupLine], _ upcoming: [String]) async throws
        -> CatchupTurnReply
    typealias Record = (_ sessionId: String, _ lines: [CatchupLine]) async throws -> Void

    /// An answer Cicada read from the person's words, waiting for their tap — "agent proposes, user disposes"
    /// (coordinator's ruling on #509 after a live misread): a reading from typed words is never applied on its own.
    struct Confirmation: Equatable {
        let itemId: String
        let resolution: QuestionResolution
        /// The proposal in words: "Note it as “Paused”?", or for a chain's pair "Join A and B as one?"
        let label: String
        /// A chain's typed answer covers its other pairs too: after this one, each remaining pair is proposed in turn
        /// ("And C and B?"), still one tap each (#536 review).
        var cascades = false
    }

    let sessionId = "catchup-" + UUID().uuidString.lowercased()
    /// The memory the chat is about: a bank switch ends it (ids repeat across banks).
    let bank: String
    private(set) var lines: [CatchupLine] = []
    private(set) var currentId: String?
    /// How many questions were put so far, and how many the session started with ("3 of 6").
    private(set) var asked = 0
    let total: Int
    var draft = ""
    private(set) var waiting = false
    private(set) var confirmation: Confirmation?
    private(set) var tapsOnly = false
    private(set) var finished = false
    private var stored: Mood = .asking
    private var queue: [String]
    private let items: () -> [InboxItem]
    private let hold: (InboxItem, QuestionResolution) -> Bool
    private let heldId: () -> String?
    private let release: () -> InboxItem?
    private let turn: Turn
    private let record: Record
    private var recording: Task<Void, Never>?

    /// The upcoming questions a reply may move to (`catchup_chat.MAX_UPCOMING`).
    static let upcomingOffered = 8

    init(queue: [String], bank: String = "", items: @escaping () -> [InboxItem],
         hold: @escaping (InboxItem, QuestionResolution) -> Bool, heldId: @escaping () -> String?,
         release: @escaping () -> InboxItem?, turn: @escaping Turn, record: @escaping Record) {
        self.queue = queue
        self.bank = bank
        self.total = queue.count
        self.items = items
        self.hold = hold
        self.heldId = heldId
        self.release = release
        self.turn = turn
        self.record = record
    }

    /// The app's own session: the Store's questions, the Inbox's hold, the backend's turn and record.
    static func live(queue: [String], store: Store, inbox: InboxViewModel) -> CatchupSession {
        CatchupSession(
            queue: queue, bank: store.bank, items: { store.visibleInbox },
            hold: { item, resolution in inbox.answer(item, resolution) },
            heldId: { inbox.held?.id },
            release: { inbox.undo(reopen: false) },
            turn: { try await APIClient.shared.catchupTurn(itemId: $0, message: $1, history: $2, upcoming: $3) },
            record: { try await APIClient.shared.catchupRecord(sessionId: $0, lines: $1) })
    }

    var mood: Mood {
        if waiting { return .thinking }
        if !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return .listening }
        return finished ? .idle : stored
    }

    /// The question being asked: for a same-person chain, its first pair still open.
    var current: InboxItem? {
        let open = items()
        if let chain = currentChain {
            return chain.lazy.compactMap { id in open.first { $0.id == id } }.first
        }
        return currentId.flatMap { id in open.first { $0.id == id } }
    }
    var chips: [CatchupChip] { current.map { CatchupAnswers.chips($0, open: items()) } ?? [] }
    /// The same-person chain being asked (#501's grouping): asked once, answered pair by pair.
    private(set) var currentChain: [String]?
    /// The answer still in its Undo window, if this chat made it.
    var undoableId: String? { heldId() }
    var position: Int { min(max(asked, 1), max(total, 1)) }

    // MARK: - Asking

    func start() {
        guard lines.isEmpty else { return }
        say(Copy.Catchup.opening, itemId: nil)
        advance(preferred: nil, alreadyAsked: false)
    }

    /// The next question: the one a reply moved to (already asked in its words), else the next in line, asked in its
    /// plain words with its reason. A question answered elsewhere meanwhile is passed over.
    private func advance(preferred: String?, alreadyAsked: Bool) {
        let open = Set(items().map(\.id))
        queue.removeAll { !open.contains($0) || $0 == currentId }
        let next: String?
        if let preferred, queue.contains(preferred) {
            next = preferred
        } else {
            next = queue.first
        }
        guard let next, let item = items().first(where: { $0.id == next }) else {
            currentId = nil
            finished = true
            stored = .pleased
            say(Copy.Catchup.done, itemId: nil)
            return
        }
        queue.removeAll { $0 == next }
        currentId = next
        currentChain = item.isChain ? item.chain : nil
        asked += 1
        stored = .asking
        if !(alreadyAsked && preferred == next) { ask(item) }
    }

    private func ask(_ item: InboxItem) {
        let reason = item.askReason.map { " " + $0 } ?? ""
        say(item.askText + reason, itemId: item.id)
    }

    private func say(_ text: String, itemId: String?) {
        lines.append(CatchupLine(.cicada(text, itemId: itemId)))
    }

    // MARK: - Answers

    /// A tap on one of the question's answers (DR-42): the inbox's own resolution, held for Undo.
    func tap(_ chip: CatchupChip) {
        guard let asked = current, !waiting else { return }
        let item = chip.itemId.flatMap { id in items().first { $0.id == id } } ?? asked
        confirmation = nil
        lines.append(CatchupLine(.tap(chip.label, itemId: item.id)))
        if let resolution = chip.resolution {
            apply(item, resolution)
            // A chain stays until each of its pairs is answered or skipped (one tap per pair, ruling 41).
            if currentChain != nil, current != nil {
                stored = .asking
                keep()
                return
            }
        } else {
            say(Copy.Catchup.skipped, itemId: nil)
        }
        currentChain = nil
        advance(preferred: nil, alreadyAsked: false)
        keep()
    }

    /// *Yes* on a proposal: the reading is applied through the inbox's hold, with the person's located words attached.
    func confirm() {
        guard let pending = confirmation, let item = items().first(where: { $0.id == pending.itemId }) else {
            confirmation = nil
            return
        }
        confirmation = nil
        apply(item, pending.resolution)
        if currentChain != nil, let next = current {
            // A chain stays until each pair is answered (#536 review): a typed "all the same" proposes the next pair,
            // named, for its own tap; otherwise its chips wait.
            if pending.cascades,
               let resolution = CatchupAnswers.merge(next, same: pending.resolution.action == "merge") {
                var carried = resolution
                carried.quote = pending.resolution.quote
                carried.sessionId = pending.resolution.sessionId
                confirmation = Confirmation(itemId: next.id, resolution: carried,
                                            label: CatchupAnswers.proposal(next, carried, also: true), cascades: true)
            }
            stored = .asking
        } else if item.id == currentId || currentChain != nil {
            currentChain = nil
            advance(preferred: nil, alreadyAsked: false)
        }
        keep()
    }

    /// *Not quite* on a proposal: nothing is applied; the question stays and the person says it again in their words.
    func notQuite() {
        guard confirmation != nil else { return }
        confirmation = nil
        stored = .asking
    }

    @discardableResult
    private func apply(_ item: InboxItem, _ resolution: QuestionResolution) -> Bool {
        guard hold(item, resolution) else { return false }
        lines.append(CatchupLine(.noted(CatchupAnswers.noted(item, resolution), heldId: item.id)))
        stored = .pleased
        return true
    }

    /// Undo on a noted line: the held answer is dropped unsent and its question is asked again.
    func undo(_ heldId: String) {
        guard self.heldId() == heldId, let item = release() else { return }
        // The undone answer leaves the chat: its tap and its receipt (review B1). What the person typed stays — those
        // are their own words whatever was read from them.
        if let i = lines.lastIndex(where: { if case .noted(_, heldId) = $0.kind { true } else { false } }) {
            lines.remove(at: i)
        }
        if let i = lines.lastIndex(where: { if case .tap(_, heldId) = $0.kind { true } else { false } }) {
            lines.remove(at: i)
        }
        if let currentId, currentId != item.id, !(currentChain ?? []).contains(item.id) {
            queue.insert(currentId, at: 0)
        }
        currentId = item.id
        currentChain = item.isChain ? item.chain : nil
        stored = .asking
        ask(item)
        keep()
    }

    /// The person's own words. With an engine: one turn, which may follow up, rephrase, move on or read an answer.
    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !waiting, let item = current else { return }
        draft = ""
        confirmation = nil
        lines.append(CatchupLine(.you(text)))
        keep()
        if tapsOnly {
            offerOwnWords(item, text, aside: nil)
            return
        }
        waiting = true
        let history = Array(lines.dropLast())
        let upcoming = Array(queue.prefix(Self.upcomingOffered))
        let reply: CatchupTurnReply
        do {
            reply = try await turn(item.id, text, history, upcoming)
        } catch APIError.httpError(404, _) {
            waiting = false
            lines.append(CatchupLine(.aside(Copy.Catchup.notOpen)))
            advance(preferred: nil, alreadyAsked: false)
            return
        } catch {
            waiting = false
            offerOwnWords(item, text, aside: Copy.Catchup.didNotCatch)
            return
        }
        waiting = false
        take(reply, item: item, text: text)
        keep()
    }

    /// What a turn's answer does to the chat: the reply said, a reading applied or offered, and where the talk goes.
    func take(_ reply: CatchupTurnReply, item: InboxItem, text: String) {
        guard reply.engine else {
            tapsOnly = true
            offerOwnWords(item, text, aside: Copy.Catchup.tapsOnly(reply.why))
            return
        }
        guard let words = reply.reply, !words.isEmpty else {
            offerOwnWords(item, text, aside: Copy.Catchup.didNotCatch)
            return
        }
        // A reading from typed words is only ever a proposal (the coordinator's ruling on #509): the person's tap
        // applies it. So is "ask me another day" — deferring is an answer too. Until they tap, the talk stays here.
        if let reading = reply.reading,
           let resolution = CatchupAnswers.resolution(item, reading, sessionId: sessionId) {
            confirmation = Confirmation(itemId: item.id, resolution: resolution,
                                        label: CatchupAnswers.proposal(item, resolution),
                                        cascades: item.isChain && ["merge", "reject"].contains(resolution.action))
        } else if reply.move == "later" {
            let later = QuestionResolution(action: "defer", remindDays: 7)
            confirmation = Confirmation(itemId: item.id, resolution: later, label: CatchupAnswers.proposal(item, later))
        }
        if confirmation != nil {
            say(words, itemId: currentId)
            if reply.move == "stop" { stop() } else { stored = .asking }
            return
        }
        let moving = ["next", "pass"].contains(reply.move)
        say(words, itemId: moving ? reply.nextId : (reply.nextId ?? currentId))
        switch reply.move {
        case "stop":
            stop()
        case "next", "pass":
            // Nothing is written: the question stays open in the list, and the talk moves on.
            advance(preferred: reply.nextId, alreadyAsked: reply.nextId != nil)
        default:
            stored = .asking   // a follow-up on the same question
        }
    }

    /// The person's words as a free answer, offered for one tap, when the question takes words; else a gentle line.
    private func offerOwnWords(_ item: InboxItem, _ text: String, aside: String?) {
        if let aside { lines.append(CatchupLine(.aside(aside))) }
        if let resolution = CatchupAnswers.ownWords(item, text) {
            confirmation = Confirmation(itemId: item.id, resolution: resolution,
                                        label: CatchupAnswers.proposal(item, resolution))
        }
        stored = .asking
    }

    func stop() {
        guard !finished else { return }
        finished = true
        currentId = nil
        confirmation = nil
        say(Copy.Catchup.stopped, itemId: nil)
        keep()
    }

    // MARK: - The record

    /// Keep the chat (one episode per session) once the person has said something; posts never overlap, so a later
    /// post always carries the longer chat.
    private func keep() {
        guard lines.contains(where: { if case .you = $0.kind { return true } else { return false } }) else { return }
        let snapshot = lines
        let previous = recording
        let record = record
        let sessionId = sessionId
        recording = Task {
            await previous?.value
            try? await record(sessionId, snapshot)
        }
    }

    /// Tests: wait for the record posts started so far.
    func settled() async { await recording?.value }
}
