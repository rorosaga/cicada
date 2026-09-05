import SwiftUI

/// Everything `sleepBubbleText` needs to pick a line, gathered by the caller
/// (`SleepView`) from the same status/debt/queue data it already holds — the
/// function itself never reaches into a view model (G125 R8: clock-free,
/// side-effect-free, so a snapshot test never flakes).
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
        case 3: return "Two of these disagree. Noting it."
        case 4: return "I think I see a habit here."
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

/// The Sleep page's speech bubble (G125): a small rounded plate with a
/// triangular tail pointing at the mascot, carrying whatever
/// `sleepBubbleText` returns. `tail` names the edge the mascot sits on, so
/// the caller can flip the tail without the bubble knowing its own layout
/// context.
struct SpeechBubbleView: View {
    let text: String
    var tail: Edge = .bottom

    private let tailSize: CGFloat = 8

    var body: some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .fill(CicadaTheme.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
            .overlay(alignment: tailAlignment) { tailShape }
            .frame(maxWidth: 260, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Cicada says: \(text)")
    }

    private var tailAlignment: Alignment {
        switch tail {
        case .top: .top
        case .bottom: .bottom
        case .leading: .leading
        case .trailing: .trailing
        }
    }

    /// A small triangle pointing away from the bubble toward the mascot,
    /// drawn (not an asset) for the same portability reason the sprites are
    /// code-defined pixel grids — no image pipeline anywhere in the mascot.
    @ViewBuilder
    private var tailShape: some View {
        Path { path in
            switch tail {
            case .bottom:
                path.move(to: CGPoint(x: -tailSize, y: 0))
                path.addLine(to: CGPoint(x: tailSize, y: 0))
                path.addLine(to: CGPoint(x: 0, y: tailSize))
            case .top:
                path.move(to: CGPoint(x: -tailSize, y: 0))
                path.addLine(to: CGPoint(x: tailSize, y: 0))
                path.addLine(to: CGPoint(x: 0, y: -tailSize))
            case .leading:
                path.move(to: CGPoint(x: 0, y: -tailSize))
                path.addLine(to: CGPoint(x: 0, y: tailSize))
                path.addLine(to: CGPoint(x: -tailSize, y: 0))
            case .trailing:
                path.move(to: CGPoint(x: 0, y: -tailSize))
                path.addLine(to: CGPoint(x: 0, y: tailSize))
                path.addLine(to: CGPoint(x: tailSize, y: 0))
            }
        }
        .fill(CicadaTheme.surfaceElevated)
        .frame(width: tailSize * 2, height: tailSize)
        .offset(x: tail == .bottom || tail == .top ? 20 : 0,
                y: tail == .bottom ? tailSize : (tail == .top ? -tailSize : 0))
    }
}
