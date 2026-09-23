import CoreGraphics
import Foundation
import Observation

/// A completion seen at the status edge, waiting for its commit (Z-P17):
/// `SleepViewModel`'s poll flips `status` to idle before `load()` refetches
/// history, so the edge and the commit it produced can arrive apart.
/// `baseline` is the newest sleep commit the page knew BEFORE the cycle —
/// taken at the start edge when it could be (Task 8 review r1, see
/// `RunStart`). `at` bounds how long the edge may wait (`pendingLifetime`).
struct PendingCompletion: Equatable {
    let baseline: String?
    let at: Date
}

/// The newest sleep commit the page knew when it saw a cycle START (Task 8
/// review r1). The backend commits in `_finalize` and only flips `status` to
/// idle after the engine-independent tail (state refresh, connector and feed
/// polls, the link backfill), several seconds later. Inside that window the
/// live unprocessed count moves, `SleepView`'s reconcile calls `load()`, and
/// history already holds the new commit — so a baseline read at the idle edge
/// IS the new commit and the completion never resolves. A cycle's commit
/// cannot exist before the cycle starts, so the start edge is the one moment
/// the baseline is certainly older than it.
struct RunStart: Equatable {
    let baseline: String?
}

/// The room's own interaction state (Track Z §6, §8).
///
/// Observation scoping is the performance budget (§10): `gaze` and
/// `pointerInRoom` are written only when they CHANGE (about two writes per
/// sweep), and only `WormStage` and the sentence slot read them, so the
/// page's body never re-evaluates for a moving pointer. The perk's
/// bookkeeping is `@ObservationIgnored` — nothing draws it.
///
/// Every decision is a static pure function (`nextAnswerIndex`,
/// `shouldPerk`, `beatAllowed`) so `RoomModelTests` pins the rules without a
/// view or a clock; the instance methods only sequence them.
@Observable
@MainActor
final class RoomModel {
    var gaze: Gaze = .center
    var pointerInRoom = false
    var reaction: ActiveReaction?
    /// `nil` = the status sentence; otherwise the answer rung on show (§6.3).
    var answerIndex: Int?
    var pointerInSentence = false
    /// Track Z Z6 (I5, I7) — the origin whose spine or Details row is under
    /// the pointer, so the other one of the pair can answer it. Written only
    /// on a change (`hover(origin:inside:)`).
    var hoveredOrigin: String?
    /// Z-P25 — one lamp popover, two anchors: which control presented it, or
    /// `nil` while it is closed.
    var lampPopover: LampAnchor?
    /// Track Z Z8 (I11) — the window's legend, the weather's text twin.
    var legendShown = false
    /// T7's link target — the commit the last real completion produced.
    /// Cleared on click, when the next cycle starts, and (by construction —
    /// `SleepView` owns this model as `@State`) when the page goes away.
    var recentCycleCommit: String?
    /// Track Z Z9 (I12–I14) — where a drag is over the room; nil when none.
    /// Written only on a change, and read only by `WormStage`, the outline and
    /// the slot (§10: a drag redraws the leaves, never the page).
    var drag: RoomDrag?
    /// I15 — what the last drop came to, while the slot still tells it (Z-B9).
    var feedResult: FeedResult?
    /// Nothing draws a pending edge, so it is not observed (§10).
    @ObservationIgnored var pendingCompletion: PendingCompletion?
    /// Set at the start edge only when history had loaded by then; consumed
    /// by whichever end edge comes next (§10: nothing draws it either).
    @ObservationIgnored var runStart: RunStart?

    @ObservationIgnored private var pointerInWorm = false
    @ObservationIgnored private var lastPerkAt: Date?

    /// I1 + I2 — one call per hover event from `StudyRoom`'s one
    /// `onContinuousHover`. `location` is top-left, in the room's space;
    /// `nil` means the pointer left the room.
    func pointer(at location: CGPoint?, scene: DeskSceneLayout, spots: [DeskHotspot: CGRect],
                 state: BookwormState, now: Date = Date(), reduceMotion: Bool) {
        let inRoom = location != nil
        if pointerInRoom != inRoom { pointerInRoom = inRoom }
        let next = gazeFor(pointerX: location?.x, layout: scene, previous: gaze, state: state)
        if next != gaze { gaze = next }
        let inWorm = location.map { point in
            spots[.worm]?.contains(sceneBottomLeading(point, in: scene)) ?? false
        } ?? false
        // The perk is an EDGE (the pointer reaching the worm), never a level:
        // hovering over it plays nothing further.
        guard inWorm != pointerInWorm else { return }
        pointerInWorm = inWorm
        guard inWorm, Self.shouldPerk(lastPerkAt: lastPerkAt, now: now),
              play(.perk, state: state, now: now, reduceMotion: reduceMotion) else { return }
        lastPerkAt = now
    }

    /// I3 — steps the ladder and plays the talk beat (sleep-talk while
    /// sleeping, none in words-only states). Returns the rung now showing, or
    /// `nil` when the click went past the last one (back to the status).
    @discardableResult
    func poke(answerCount: Int, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Int? {
        // Z-B11 — a poke asks a new question; a finished feed line gives way.
        if feedResult?.isTerminal == true { feedResult = nil }
        answerIndex = Self.nextAnswerIndex(after: answerIndex, count: answerCount)
        if answerIndex != nil { play(.talk, state: state, now: now, reduceMotion: reduceMotion) }
        return answerIndex
    }

    /// I4 — Esc, a mood change, the dwell. Writes only when an answer is up,
    /// so a mood change on a page nobody poked costs no observation.
    func dismissAnswers() {
        if answerIndex != nil { answerIndex = nil }
    }

    /// I5 / I7 — one spine or row reports the pointer. An exit clears the
    /// highlight only if it still names this origin: moving from row A to
    /// row B can deliver B's enter BEFORE A's exit, and a plain
    /// `inside ? origin : nil` would then wipe B's highlight.
    func hover(origin: String, inside: Bool) {
        if inside {
            if hoveredOrigin != origin { hoveredOrigin = origin }
        } else if hoveredOrigin == origin {
            hoveredOrigin = nil
        }
    }

    // MARK: Feeding (Track Z Z9, §7.4)

    /// I12/I13 — `DropInfo.location` is top-left in the room's space. Over the
    /// worm's hotspot the worm is eager; elsewhere it looks toward the drag
    /// with the pointer's own hysteresis (`gazeFor`). A new drag replaces
    /// whatever the last drop said (Z-B11).
    func dragMoved(to location: CGPoint, scene: DeskSceneLayout, spots: [DeskHotspot: CGRect], state: BookwormState) {
        let inWorm = spots[.worm]?.contains(sceneBottomLeading(location, in: scene)) ?? false
        var previous = Gaze.center
        if case .overRoom(let gaze) = drag { previous = gaze }
        let next: RoomDrag = inWorm ? .overWorm
            : .overRoom(gazeFor(pointerX: location.x, layout: scene, previous: previous, state: state))
        if drag != next { drag = next }
        if feedResult?.isTerminal == true { feedResult = nil }
    }

    /// I14 — the drag left the room, or dropped.
    func dragEnded() {
        if drag != nil { drag = nil }
    }

    /// I15 — the drop's result: the line, and the beat §6.4 allows (Z-B10).
    /// A sleeping or erroring worm plays nothing and stays as it is; Reduce
    /// Motion plays nothing. Returns whether a beat started.
    @discardableResult
    func fed(_ result: FeedResult, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Bool {
        dragEnded()
        dismissAnswers()
        feedResult = result
        return play(Self.beat(for: result), state: state, now: now, reduceMotion: reduceMotion)
    }

    /// Z-B10 — one gesture for yes, one for no.
    static func beat(for result: FeedResult) -> BookwormReaction {
        result == .handedOver ? .gulp : .shake
    }

    /// Follows the router's phase (the slot's `onChange`). A drop the room
    /// handed over lands as a `.landed` line when the done card closes; a
    /// cancel or a failure closes back to the status. Returns the landing so
    /// the slot can announce it — the person pressed Done (§11).
    @discardableResult
    func intakeChanged(from old: IntakePhase, to new: IntakePhase) -> FeedLanding? {
        guard feedResult == .handedOver, new == .idle else { return nil }
        guard case .done(let outcome) = old else {
            feedResult = nil
            return nil
        }
        let landing = FeedLanding(outcome)
        feedResult = .landed(landing)
        return landing
    }

    /// Esc, the dwell, a mood change (Z-B11): back to the status — the answer
    /// on show and any feed line about a moment that has passed. A live
    /// intake's line stays, because it is still true.
    func dismissSlot() {
        dismissAnswers()
        if feedResult?.isTerminal == true { feedResult = nil }
    }

    /// Which feed line the slot shows, if any (§7.4, Z-B9). A drag in
    /// progress outranks the last drop; a handed-over drop follows the
    /// router's own phase until the panel closes.
    static func feedPhase(drag: RoomDrag?, result: FeedResult?, intakePhase: IntakePhase) -> FeedPhase? {
        if let drag { return .armed(overWorm: drag == .overWorm) }
        guard let result else { return nil }
        switch result {
        case .handedOver: return FeedPhase(intakePhase)
        case .landed(let landing): return .landed(landing)
        case .refused(let refusal): return .refused(refusal)
        case .busy: return .busy
        case .unreachable: return .unreachable
        }
    }

    // MARK: The completion edge (Task 8, §6.5, Z-P17)

    /// How long a completion may wait for its commit (Task 8 review r1). The
    /// commit is written before the idle edge, and the poll's own `load()`
    /// follows the edge within a round-trip, so a real one arrives in
    /// seconds. An edge that committed nothing (an idle night) would
    /// otherwise stay armed until some LATER cycle's commit — one whose
    /// running edge this page never saw (a scheduled run while the page sat
    /// unpolled, or a sub-second cycle) — and cheer for a cycle whose cancel
    /// and error state were never checked.
    static let pendingLifetime: TimeInterval = 120

    /// Test seam kept for the pure rules; `SleepView` goes through
    /// `cycleEnded`, which picks the baseline.
    func recordCompletion(baseline: String?, at date: Date) {
        pendingCompletion = PendingCompletion(baseline: baseline, at: date)
    }

    /// Returns the commit the first time history brings it, else `nil` — so
    /// the caller cheers exactly once per completion, however many history
    /// refreshes follow. An edge older than `pendingLifetime` is dropped
    /// unresolved.
    func resolveCompletion(history: [SleepHistoryEntry], now: Date = Date()) -> String? {
        guard let pending = pendingCompletion else { return nil }
        guard now.timeIntervalSince(pending.at) <= Self.pendingLifetime else {
            pendingCompletion = nil
            return nil
        }
        guard let commit = completedCommit(baseline: pending.baseline, history: history) else { return nil }
        pendingCompletion = nil
        recentCycleCommit = commit
        return commit
    }

    /// A new cycle makes the last one's link stale ("what changed" would now
    /// be two cycles ago), and drops any edge still waiting for its commit.
    /// `baseline` is the newest sleep commit in history right now; it is kept
    /// only when `historyLoaded`, since a page opened mid-run can see this
    /// edge before its first history fetch lands (an empty list that means
    /// "not yet", not "no cycles").
    func cycleStarted(baseline: String?, historyLoaded: Bool) {
        pendingCompletion = nil
        runStart = historyLoaded ? RunStart(baseline: baseline) : nil
        if recentCycleCommit != nil { recentCycleCommit = nil }
    }

    /// Any running → not-running edge. Consumes the start baseline either way
    /// (a cancel must not leave it for a later cycle whose start this page
    /// missed). A real completion records its edge against the start
    /// baseline — or, when the page never saw the start with history loaded,
    /// the edge-time one, which can only err toward no cheer — and resolves
    /// at once against the history already in hand: when the reconcile load
    /// brought the commit during the backend's tail, no later history change
    /// will come to resolve it. Returns the commit when it resolved here.
    func cycleEnded(real: Bool, edgeBaseline: String?, history: [SleepHistoryEntry],
                    at date: Date = Date()) -> String? {
        let start = runStart
        runStart = nil
        guard real else { return nil }
        recordCompletion(baseline: start.map(\.baseline) ?? edgeBaseline, at: date)
        return resolveCompletion(history: history, now: date)
    }

    /// The link was followed: hand back its commit and clear it.
    func followWhatChanged() -> String? {
        defer { recentCycleCommit = nil }
        return recentCycleCommit
    }

    /// Starts a beat if §6.4 allows it for `state` and Reduce Motion is off.
    @discardableResult
    func play(_ kind: BookwormReaction, state: BookwormState, now: Date = Date(), reduceMotion: Bool) -> Bool {
        guard Self.beatAllowed(kind, state: state, reduceMotion: reduceMotion) else { return false }
        reaction = ActiveReaction(kind: kind, startedAt: now, id: UUID())
        return true
    }

    /// Clears a beat once its frames have played (≤ 0.36 s, R-Z12) — unless a
    /// newer beat replaced it meanwhile.
    func settleReaction() async {
        guard let playing = reaction else { return }
        try? await Task.sleep(for: .seconds(SleepMotion.beatFrameInterval * Double(SleepMotion.maxBeatFrames)))
        if reaction?.id == playing.id { reaction = nil }
    }

    /// One click past the last rung returns to the status sentence (§6.3):
    /// the ladder is a loop through the status, never a dead end. An index
    /// the ladder has shrunk under (the inbox rung went away while an answer
    /// was up) restarts at the first rung (Task 6 review r1) — mapping it to
    /// `nil` made that click show nothing and play no beat.
    static func nextAnswerIndex(after current: Int?, count: Int) -> Int? {
        guard count > 0 else { return nil }
        guard let current, current < count else { return 0 }
        return current + 1 < count ? current + 1 : nil
    }

    static func shouldPerk(lastPerkAt: Date?, now: Date) -> Bool {
        guard let lastPerkAt else { return true }
        return now.timeIntervalSince(lastPerkAt) >= SleepMotion.perkCooldown
    }

    /// R-Z3 (a response never contradicts state art, the §6.4 matrix) and
    /// R-Z12 (Reduce Motion reaches the terminal frame: no beat at all).
    static func beatAllowed(_ kind: BookwormReaction, state: BookwormState, reduceMotion: Bool) -> Bool {
        !reduceMotion && state.allows(kind)
    }
}
