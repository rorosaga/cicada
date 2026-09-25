import SwiftUI

/// Everything `sleepBubbleText` needs to pick a line, gathered by the caller
/// from the status/debt/queue data it already holds — the function itself
/// never reaches into a view model (G125 R8: clock-free, side-effect-free, so
/// a snapshot test never flakes).
///
/// Track Z Z2 retired the Sleep page's bubble (R-Z5: the worm speaks in one
/// slot under the room, `roomSentence`). This context and `sleepBubbleText`
/// stay as a shared pure function — round 3's other designs reuse the lines
/// for Home's footer (design §3, R-A4 amended).
struct BubbleContext: Equatable {
    var unprocessed: Int = 0
    var topOriginLabel: String?
    var topOriginCount: Int = 0
    var stage: Int = 0
    var read: Int = 0
    var total: Int = 0
    var hoursSinceLastCycle: Double?
}

/// What the worm says (G125). Pure and clock-free (R8): the variant is
/// `(unprocessed + stage) % lines.count`, so the line changes when the state
/// does and never flickers between renders.
func sleepBubbleText(_ state: BookwormState, _ ctx: BubbleContext) -> String {
    let n = ctx.unprocessed
    func pick(_ lines: [String]) -> String { lines[((n + ctx.stage) % max(1, lines.count) + lines.count) % lines.count] }
    switch state {
    case .awake: return "Listening."
    case .reading:
        var lines = ["\(n) to read. Give me a night and I'll have these."]
        if let top = ctx.topOriginLabel, ctx.topOriginCount > 0 {
            lines.insert("\(n) to read. The \(top) pile is the big one.", at: 0)
        }
        if n == 0 { lines = ["Something new just landed. Let me look."] }
        return pick(lines)
    case .sleeping(let stage):
        switch stage {
        case 1: return ctx.total > 0 ? "Reading… \(ctx.read) of \(ctx.total)." : "Reading…"
        case 2: return "Sorting out who's who."
        case 3: return "Checking for contradictions."   // design §13.3 — what the stage DOES, not a finding
        case 4: return "Looking for habits."
        default: return "Filing everything away."
        }
    case .digesting: return pick(["That was a good one.", "Filed. Give me a second."])
    case .happy: return pick(["All read. Nothing waiting.", "Caught up. Bring me something new."])
    case .curious(let count): return "\(count) waiting on you in the Inbox."
    case .hungry:
        if let h = ctx.hoursSinceLastCycle, h >= 48 {
            return "It's been \(Int(h / 24)) days. I'm behind."
        }
        return pick(["Overdue. Wake me when you can.", "\(n) to read and no night off in sight."])
    case .error: return "Last night didn't go well — see below."
    }
}
