import Foundation

/// Where the worm looks (Track Z §6.1). Three horizontal poses, not six:
/// the room is a wide, short box and the worm's own ink span is the dead
/// zone (`gazeFor`, `DeskHotspots.swift`), so left / centre / right is all
/// the pointer can honestly mean.
enum Gaze: String, Hashable, CaseIterable {
    case left, center, right
}

/// A pose the worm's frames can take — RESPONSE art (R-Z1): it acknowledges
/// the person's own gesture, carries no fact, and never contradicts the state
/// it is drawn over (§6.4). Character-agnostic on purpose (G127 would draw
/// the same four poses for another mascot).
enum BookwormPose: Hashable {
    /// Today's frames.
    case idle
    /// The pointer is in the room: the eyes follow it, with a blink.
    case attentive(Gaze)
    /// A file is being dragged over the room (Track Z §7.4 — feeding, Z9).
    case expectant(Gaze)
    /// …and over the worm itself.
    case eager

    var gaze: Gaze {
        switch self {
        case .idle, .eager: .center
        case .attentive(let gaze), .expectant(let gaze): gaze
        }
    }

    /// The renderer key's look segment; `nil` for `.idle`, which is what keeps
    /// every pre-Z4 key byte-identical.
    var keySegment: String? {
        switch self {
        case .idle: nil
        case .attentive(let gaze): "attentive.\(gaze.rawValue)"
        case .expectant(let gaze): "expectant.\(gaze.rawValue)"
        case .eager: "eager"
        }
    }

    /// What this pose becomes for `state` (§6.4) and under Reduce Motion
    /// (§6.1): the gaze is dropped — a following eye is motion — but the drop
    /// poses stay, because the armed-drop cue is a state (frame 0 is held by
    /// `BookwormView.frameIndex` anyway). A state with no gaze looks ahead.
    func effective(for state: BookwormState, reduceMotion: Bool) -> BookwormPose {
        switch self {
        case .idle:
            return .idle
        case .attentive(let gaze):
            return state.acceptsGaze && !reduceMotion ? .attentive(gaze) : .idle
        case .expectant(let gaze):
            guard state.acceptsDropPose else { return .idle }
            return .expectant(state.acceptsGaze ? gaze : .center)
        case .eager:
            return state.acceptsDropPose ? .eager : .idle
        }
    }
}

/// A short beat — at most three frames at `BookwormSprites.reactionInterval`
/// (≤ 0.36 s, R-Z12). `gulp` and `shake` are feeding's (Z9); `perk`, `talk`
/// and `cheer` are used from Task 6 on.
enum BookwormReaction: String, Hashable, CaseIterable {
    case perk, talk, gulp, shake, cheer

    /// Whether the frames depend on where the worm is looking.
    var followsGaze: Bool { self == .perk || self == .talk || self == .shake }
}

/// A beat in flight. `id` is what `WormStage`'s `.task(id:)` settles on, so a
/// second beat started mid-beat restarts the clock rather than being cut short.
struct ActiveReaction: Equatable {
    let kind: BookwormReaction
    let startedAt: Date
    let id: UUID
}

/// One thing the renderer can draw for a state: a pose loop or a beat.
/// Z-P10: a beat replaces the pose's frames, so it is keyed by the gaze it
/// plays at — never by pose × reaction, which would multiply the key set for
/// no visible difference.
enum BookwormLook: Hashable {
    case pose(BookwormPose)
    case reaction(BookwormReaction, Gaze)

    static let idle = BookwormLook.pose(.idle)

    var keySegment: String? {
        switch self {
        case .pose(let pose): pose.keySegment
        case .reaction(let reaction, let gaze): "\(reaction.rawValue).\(gaze.rawValue)"
        }
    }

    /// Every look §6.4 lets `state` show — the renderer's reachable key set,
    /// and the union the window's occlusion test masks with (Task 9).
    static func reachable(for state: BookwormState) -> [BookwormLook] {
        let gazes: [Gaze] = state.acceptsGaze ? Gaze.allCases : [.center]
        var looks: [BookwormLook] = [.idle]
        if state.acceptsGaze { looks += Gaze.allCases.map { .pose(.attentive($0)) } }
        if state.acceptsDropPose {
            looks += gazes.map { .pose(.expectant($0)) }
            looks.append(.pose(.eager))
        }
        for reaction in BookwormReaction.allCases where state.allows(reaction) {
            looks += (reaction.followsGaze ? gazes : [.center]).map { .reaction(reaction, $0) }
        }
        return looks
    }

    /// The look a beat plays as, or `nil` when §6.4 forbids it for `state`.
    /// The gaze folds to `.center` wherever the frames ignore it, which is
    /// exactly the rule `reachable(for:)` enumerates. So a beat's renderer key
    /// is always one the Z-P10 bound counted, whatever the pointer last did.
    /// `BookwormView` asks this and never builds a `.reaction` look itself.
    static func beat(_ reaction: BookwormReaction, for state: BookwormState, gaze: Gaze) -> BookwormLook? {
        guard state.allows(reaction) else { return nil }
        return .reaction(reaction, reaction.followsGaze && state.acceptsGaze ? gaze : .center)
    }
}

/// The state × response matrix (design §6.4). "—" means suppressed so a
/// response never contradicts state art: a sleeping worm's eyes stay shut,
/// error pupils stay red. `.curious` is the menu bar's and takes nothing.
extension BookwormState {
    var acceptsGaze: Bool {
        switch self {
        case .awake, .happy, .reading, .hungry: true
        default: false
        }
    }

    var acceptsDropPose: Bool {
        switch self {
        case .awake, .happy, .reading, .hungry, .digesting: true
        default: false
        }
    }

    /// Z-P12: gulp is allowed while digesting (§6.4's matrix; §6.1's list
    /// omitted it — the matrix is the no-contradiction table).
    func allows(_ reaction: BookwormReaction) -> Bool {
        switch (reaction, self) {
        case (.perk, .awake), (.perk, .happy), (.perk, .reading), (.perk, .hungry): true
        case (.talk, .error), (.talk, .curious): false
        case (.talk, _): true
        case (.gulp, .awake), (.gulp, .happy), (.gulp, .reading), (.gulp, .hungry), (.gulp, .digesting): true
        case (.shake, .awake), (.shake, .happy), (.shake, .reading), (.shake, .hungry), (.shake, .digesting): true
        case (.cheer, .happy), (.cheer, .digesting): true
        default: false
        }
    }
}
