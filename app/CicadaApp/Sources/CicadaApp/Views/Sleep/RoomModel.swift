import CoreGraphics
import Foundation
import Observation

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
