import Foundation

/// Onboarding's *Meet your bookworm* step (owner 2026-10-23), decided purely so the view only renders it
/// (`MenuBarStepTests`). The worm is the menu bar's own 18 × 18 sprite with its code-drawn badge (`BookwormRenderer`),
/// shown big. It counts up the way the badge does as conversations arrive, holds, then an illustrated Sleep (the
/// sprite's stage dots) takes the number away, and it starts again.
///
/// The number is the badge's own source: `StatusSnapshot.waitingForSleep`, the conversations Sleep itself would read
/// (`GET /status` `episodes.readable`). When some already wait — the person brought things in on Sources — the count
/// lands on that real number and says so ("3 waiting now"); when none do, it counts an example and says *For example*,
/// so an illustration is never read as the person's own count.
enum MenuBarStepModel {
    /// The example's number: big enough to read as a pile, small enough to count one by one.
    static let exampleCount = 12

    struct Beat: Equatable {
        let state: BookwormState
        let hold: TimeInterval
    }

    /// The number the count lands on: the person's real waiting count when there is one, else the example.
    static func target(waiting: Int?) -> Int {
        guard let waiting, waiting > 0 else { return exampleCount }
        return waiting
    }

    static func isExample(waiting: Int?) -> Bool { (waiting ?? 0) <= 0 }

    /// The caption under the worm: the real count in words, or that it is an example.
    static func caption(waiting: Int?) -> String {
        guard let waiting, waiting > 0 else { return Copy.MeetWorm.example }
        return Copy.MeetWorm.waitingNow(waiting)
    }

    /// The values the badge shows on its way up: one by one to a small number; in at most `maxSteps` even, strictly
    /// increasing jumps to a large one. Always ends on the target; never empty for a target of 1 or more.
    static func countSteps(to target: Int, maxSteps: Int = CicadaMotion.wormCountMaxSteps) -> [Int] {
        guard target > 0 else { return [] }
        let steps = max(1, maxSteps)
        if target <= steps { return Array(1...target) }
        var values: [Int] = []
        for i in 1...steps {
            let v = max(1, Int((Double(target) * Double(i) / Double(steps)).rounded()))
            if v > (values.last ?? 0) { values.append(v) }
        }
        if values.last != target { values.append(target) }
        return values
    }

    /// One loop of the illustration: nothing waiting, the count going up, a hold on the number, Sleep's five stage
    /// dots, and back to nothing waiting (the next loop's first beat).
    static func beats(target: Int) -> [Beat] {
        var beats = [Beat(state: .happy, hold: CicadaMotion.wormCountRest)]
        let counts = countSteps(to: target)
        for (i, n) in counts.enumerated() {
            beats.append(Beat(state: .curious(count: n),
                              hold: i == counts.count - 1 ? CicadaMotion.wormCountHold : CicadaMotion.wormCountTick))
        }
        for stage in 1...5 { beats.append(Beat(state: .sleeping(stage: stage), hold: CicadaMotion.wormSleepTick)) }
        return beats
    }

    /// Reduce Motion: the moving value is gated too (DR-66) — the worm holds on the number the copy explains.
    static func still(target: Int) -> BookwormState { .curious(count: target) }
}
