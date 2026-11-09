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
/// follow-up, the question in other words, or a move to a related question it was offered. What their words clearly
/// settled is applied at once through the same hold, every part of it under one Undo, and said in one line (owner
/// 2026-11-05: "if the agent is going to ask for confirmation on everything eventhough i just told him then thats bad
/// user experience"); a misread is one Undo away, and what stayed unclear is the reply. With no engine to answer, the chat takes taps (and the person's own
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

    /// The person's raw words as a free answer, waiting for their tap: only where no model read them (no engine, or
    /// no usable reply), so nothing judged they answered the question.
    struct Confirmation: Equatable {
        let itemId: String
        let resolution: QuestionResolution
        /// The proposal in words: "Note it as “Paused”?"
        let label: String
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
    private let holdAll: (([(item: InboxItem, resolution: QuestionResolution)]) -> Bool)?
    private let heldId: () -> String?
    private let release: () -> InboxItem?
    private let turn: Turn
    private let record: Record
    private var recording: Task<Void, Never>?
    /// *Answer* on Home (item 1): the chat opens on the lead question itself, with what its card is about, not on the
    /// generic greeting.
    private let leadsWithContext: Bool

    /// The upcoming questions a reply may move to (`catchup_chat.MAX_UPCOMING`).
    static let upcomingOffered = 8

    init(queue: [String], bank: String = "", items: @escaping () -> [InboxItem],
         hold: @escaping (InboxItem, QuestionResolution) -> Bool, heldId: @escaping () -> String?,
         release: @escaping () -> InboxItem?, turn: @escaping Turn, record: @escaping Record,
         holdAll: (([(item: InboxItem, resolution: QuestionResolution)]) -> Bool)? = nil,
         leadsWithContext: Bool = false) {
        self.leadsWithContext = leadsWithContext
        self.queue = queue
        self.bank = bank
        self.total = queue.count
        self.items = items
        self.hold = hold
        self.holdAll = holdAll
        self.heldId = heldId
        self.release = release
        self.turn = turn
        self.record = record
    }

    /// The app's own session: the Store's questions, the Inbox's hold, the backend's turn and record.
    static func live(queue: [String], store: Store, inbox: InboxViewModel,
                    leadsWithContext: Bool = false) -> CatchupSession {
        CatchupSession(
            queue: queue, bank: store.bank, items: { store.visibleInbox },
            hold: { item, resolution in inbox.answer(item, resolution) },
            heldId: { inbox.held?.id },
            release: { inbox.undo(reopen: false) },
            turn: { try await APIClient.shared.catchupTurn(itemId: $0, message: $1, history: $2, upcoming: $3) },
            record: { try await APIClient.shared.catchupRecord(sessionId: $0, lines: $1) },
            holdAll: { inbox.answerAll($0) }, leadsWithContext: leadsWithContext)
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
        if !leadsWithContext { say(Copy.Catchup.opening, itemId: nil) }
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
        if !(alreadyAsked && preferred == next) { ask(item, withContext: leadsWithContext && asked == 1) }
    }

    private func ask(_ item: InboxItem, withContext: Bool = false) {
        let reason = item.askReason.map { " " + $0 } ?? ""
        let context = withContext ? CatchupContext.summary(for: item).map { "\n\n" + $0 } : nil
        say(item.askText + reason + (context ?? ""), itemId: item.id)
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

    /// *Yes* on a proposal: the person's raw words go through the inbox's hold.
    func confirm() {
        guard let pending = confirmation, let item = items().first(where: { $0.id == pending.itemId }) else {
            confirmation = nil
            return
        }
        confirmation = nil
        apply(item, pending.resolution)
        moveOn(words: nil, nextId: nil)
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
        apply([CatchupAnswers.Part(item: item, resolution: resolution)])
    }

    /// One answer, however many parts: one hold, one line, one Undo.
    @discardableResult
    private func apply(_ parts: [CatchupAnswers.Part]) -> Bool {
        let ordered = CatchupAnswers.sendOrder(parts)
        guard let first = ordered.first else { return false }
        let held = holdAll?(ordered.map { ($0.item, $0.resolution) })
            ?? ordered.reduce(true) { $0 && hold($1.item, $1.resolution) }
        guard held else { return false }
        lines.append(CatchupLine(.noted(CatchupAnswers.noted(ordered), heldId: first.item.id)))
        stored = .pleased
        return true
    }

    /// After an answer: while the question being asked (or a pair of its chain) is still open the talk stays on it,
    /// else it moves on, to the question the reply asked if it asked one.
    private func moveOn(words: String?, nextId: String?) {
        if let next = current {
            if let words { say(words, itemId: next.id) }
            stored = .asking
            return
        }
        currentChain = nil
        if let words { say(words, itemId: nextId) }
        advance(preferred: nextId, alreadyAsked: nextId != nil && words != nil)
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
        finished = false   // the last answer's Undo: the question is open again, and so is the chat
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

    /// What a turn's answer does to the chat: what their words settled applied at once, the reply said, and where the
    /// talk goes. "Ask me another day" is an answer too.
    func take(_ reply: CatchupTurnReply, item: InboxItem, text: String) {
        guard reply.engine else {
            tapsOnly = true
            offerOwnWords(item, text, aside: Copy.Catchup.tapsOnly(reply.why))
            return
        }
        let words = reply.reply.flatMap { $0.isEmpty ? nil : $0 }
        var parts: [CatchupAnswers.Part] = reply.readings.compactMap { reading in
            let target = reading.itemId.flatMap { id in items().first { $0.id == id } } ?? item
            return CatchupAnswers.resolution(target, reading, sessionId: sessionId)
                .map { CatchupAnswers.Part(item: target, resolution: $0, targetName: reading.targetName) }
        }
        if parts.isEmpty, reply.move == "later" {
            let open = items()
            let asked = currentChain.map { chain in open.filter { chain.contains($0.id) } } ?? [item]
            parts = asked.map {
                CatchupAnswers.Part(item: $0, resolution: QuestionResolution(action: "defer", remindDays: 7))
            }
        }
        guard !parts.isEmpty || words != nil else {
            offerOwnWords(item, text, aside: Copy.Catchup.didNotCatch)
            return
        }
        if !parts.isEmpty, apply(parts) {
            for missing in reply.unjoined {
                lines.append(CatchupLine(.aside(Copy.Catchup.cannotJoin(missing.a, missing.b))))
            }
            if reply.move == "stop" {
                if let words { say(words, itemId: nil) }
                stop()
            } else {
                moveOn(words: words, nextId: reply.nextId)
            }
            return
        }
        // Nothing applied (a bank switch refused the hold, or there was nothing to apply): the reply is all there is.
        let moving = ["next", "pass"].contains(reply.move)
        say(words ?? Copy.Catchup.didNotCatch, itemId: moving ? reply.nextId : (reply.nextId ?? currentId))
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
