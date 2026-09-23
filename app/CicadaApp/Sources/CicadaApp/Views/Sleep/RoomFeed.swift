import SwiftUI
import UniformTypeIdentifiers

// MARK: - Feeding (Track Z Z9, design §7.4, R-Z10)
//
// Feeding is import, and only import: a drop on the room — or "Feed a file…"
// — goes to the one `IntakeRouter` (its guard, its sheet, its
// `intakeInFlight`) and to nothing else. This file is the room's side of that
// door: where a drag is, what a drop came to, and the words the worm says
// about it. There is no hunger mechanic, no nag and no reward loop, and
// feeding never "cures" `.hungry` — only a cycle does.

/// Where a drag is over the room (I12, I13) — response art's input, never a fact.
enum RoomDrag: Equatable {
    case overRoom(Gaze)
    case overWorm

    /// Expectant toward the drag, eager over the worm (§6.1). `BookwormPose
    /// .effective` folds both away where they would contradict state art (a
    /// sleeping worm keeps its nightcap and its shut eyes).
    var pose: BookwormPose {
        switch self {
        case .overRoom(let gaze): .expectant(gaze)
        case .overWorm: .eager
        }
    }
}

/// What an intake the room handed over came to, with no number in it (R-Z3:
/// one file and a thousand get the same line — the panel has the counts).
enum FeedLanding: Hashable {
    case added, nothingNew, elsewhere

    init(_ outcome: IntakeOutcome) {
        if outcome.total == 0 {
            self = .nothingNew
        } else if outcome.inactiveBank != nil {
            self = .elsewhere
        } else {
            self = .added
        }
    }
}

/// The room's record of its last drop (I15, Z-B9).
enum FeedResult: Equatable {
    /// The router took it; the router's own phase now drives the line.
    case handedOver
    /// The done card closed on a finished import — said once, then it dwells away.
    case landed(FeedLanding)
    case refused(FeedRefusal)
    case busy
    /// The page is stale (R-A12): nothing was sent.
    case unreachable
    /// The import failed while its panel was closed (final review, finding
    /// 1): said once, then it dwells away like any other ending.
    case failedUnseen

    /// Everything but a live intake ends with the moment it described (Z-B11).
    var isTerminal: Bool { self != .handedOver }

    init(_ acceptance: IntakeAcceptance) {
        switch acceptance {
        case .accepted: self = .handedOver
        case .refused(let refusal): self = .refused(refusal)
        case .busy: self = .busy
        }
    }
}

/// The line the slot shows while feeding is under way. `Hashable`: the slot
/// cross-fades on it.
enum FeedPhase: Hashable {
    case armed(overWorm: Bool)
    case refused(FeedRefusal)
    case busy
    case unreachable
    case reading
    case preview
    case importing
    case landed(FeedLanding)
    case failed
    /// `.failed` with the panel closed — "the panel says why" would point at
    /// nothing, and opening it again resets a failure (`IntakeRouter.present`).
    case failedUnseen

    /// The router's own phase, as the room tells it (Z-B9). `.idle` is no line.
    init?(_ phase: IntakePhase) {
        switch phase {
        case .idle: return nil
        case .reading: self = .reading
        case .preview: self = .preview
        case .importing: self = .importing
        case .done(let outcome): self = .landed(FeedLanding(outcome))
        case .failed: self = .failed
        }
    }
}

/// A sleeping worm stays asleep through a drop (§6.4) and says when it will read.
func feedIsAsleep(_ mood: BookwormState) -> Bool {
    if case .sleeping = mood { return true }
    return false
}

/// The feed lines (§7.4, I12–I15): pure `SentenceLine`s under R-Z13 (lead ≤ 40,
/// tail ≤ 80, no "!", no guess) with no digit at all (R-Z3), in the worm's own
/// first person (Z-B18). A line that names a service wears its mark (Z-P26).
func feedLine(_ phase: FeedPhase, asleep: Bool) -> SentenceLine {
    let afterTheNap = "I'll read it after this nap."
    switch phase {
    case .armed(let overWorm):
        // "saved links", not "notes" (Z-B18): a note is not an export the intake reads.
        return SentenceLine(lead: overWorm ? "Drop it on me." : "Is that for me?",
                            tail: asleep ? "I'll read it next cycle." : "Chat exports, bookmarks, feeds and saved links.")
    case .refused(.claudeSessions):
        return SentenceLine(lead: "I don't eat those.", tail: "Claude Code sessions come to me once it's connected.",
                            mark: .origin("claude-code"))
    case .refused(.codexSessions):
        return SentenceLine(lead: "I don't eat those.", tail: "Codex sessions come to me once it's connected.",
                            mark: .origin("codex"))
    case .refused(.cicadaHome):
        return SentenceLine(lead: "That's my own folder.", tail: "I keep my things there, so I can't eat it.")
    case .refused(.unreadable):
        return SentenceLine(lead: "I can't read that yet.", tail: "Chat exports, bookmarks, feeds and saved links work.")
    case .busy:
        return SentenceLine(lead: "I'm still eating the last one.", tail: "Drop it again when that's done.")
    case .unreachable:
        return SentenceLine(lead: "I'm offline right now.", tail: "Nothing was sent. Try again in a moment.")
    case .reading:
        return SentenceLine(lead: "Let me see what's in it.", tail: asleep ? afterTheNap : nil)
    case .preview:
        return SentenceLine(lead: "Have a look first.", tail: "Import it when it looks right.")
    case .importing:
        return SentenceLine(lead: "Adding it to the pile…", tail: asleep ? afterTheNap : nil)
    case .landed(.added):
        return SentenceLine(lead: "Got it.", tail: asleep ? afterTheNap : "It's on the pile now.")
    case .landed(.nothingNew):
        return SentenceLine(lead: "I already had all of that.")
    case .landed(.elsewhere):
        return SentenceLine(lead: "That went to another memory.", tail: "It waits there, not on this pile.")
    case .failed:
        return SentenceLine(lead: "I couldn't take that.", tail: "The panel says why.")
    case .failedUnseen:
        return SentenceLine(lead: "I couldn't take that.", tail: "Drop it again to open the panel.")
    }
}

/// I15 — a stale page answers without asking the router, so nothing is sent
/// (Z-B9); otherwise the router's answer — its guard, its busy state — is the room's.
@MainActor
func roomFeedResult(reachable: Bool, accept: () -> IntakeAcceptance) -> FeedResult {
    reachable ? FeedResult(accept()) : .unreachable
}

/// The whole room is the drop target (§7.4). The innermost target wins the
/// drop, and it claims the drag so the window's veil steps aside (Z-B8). The
/// guard runs at the drop, not during the hover (Z-B7): while a file hovers,
/// the worm is expectant for any file URL.
@MainActor
struct RoomDropDelegate: DropDelegate {
    let room: RoomModel
    let intake: IntakeRouter
    let scene: DeskSceneLayout
    let spots: [DeskHotspot: CGRect]
    let mood: BookwormState
    let onDrop: @MainActor ([URL]) -> Void

    func validateDrop(info: DropInfo) -> Bool { info.hasItemsConforming(to: [.fileURL]) }

    func dropEntered(info: DropInfo) {
        intake.claimDrop(.sleepRoom)
        room.dragMoved(to: info.location, scene: scene, spots: spots, state: mood)
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        room.dragMoved(to: info.location, scene: scene, spots: spots, state: mood)
        return DropProposal(operation: .copy)
    }

    func dropExited(info: DropInfo) {
        room.dragEnded()
        intake.releaseDrop(.sleepRoom)
    }

    /// The armed pose holds until the URLs have loaded and the router has
    /// answered — `fed` ends the drag — so the slot never flashes back to the
    /// status between the drop and its line.
    func performDrop(info: DropInfo) -> Bool {
        intake.releaseDrop(.sleepRoom)
        IntakeDrop.load(info.itemProviders(for: [.fileURL])) { urls in onDrop(urls) }
        return true
    }
}
