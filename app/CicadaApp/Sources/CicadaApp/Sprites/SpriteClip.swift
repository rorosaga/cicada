import Foundation

/// Expanded play order and per-step seconds. All clock-based frame selection lives here.
struct SpriteClip: Equatable {
    let sheet: String
    let tag: String
    let order: [Int]
    let seconds: [TimeInterval]
    var total: TimeInterval { seconds.reduce(0, +) }

    private var valid: Bool {
        !order.isEmpty && order.count == seconds.count && seconds.allSatisfy { $0.isFinite && $0 > 0 }
            && total.isFinite && total > 0
    }

    func loopStep(at date: Date, origin: Date = SpriteClock.origin, profile: SpritePlaybackProfile) -> Int {
        let elapsed = date.timeIntervalSince(origin)
        guard valid, profile != .still, elapsed.isFinite, elapsed >= 0 else { return 0 }
        let cycle = total * profile.slowdown
        guard cycle.isFinite, cycle > 0 else { return 0 }
        let phase = elapsed.truncatingRemainder(dividingBy: cycle) / profile.slowdown
        return step(at: phase)
    }

    func onceStep(at date: Date, startedAt: Date, profile: SpritePlaybackProfile) -> Int? {
        guard valid else { return nil }
        guard profile != .still else { return 0 }
        let elapsed = date.timeIntervalSince(startedAt) / profile.slowdown
        guard elapsed.isFinite else { return 0 }
        guard elapsed >= 0 else { return 0 }
        guard elapsed < total - 1e-9 else { return nil }
        return step(at: elapsed)
    }

    private func step(at phase: Double) -> Int {
        var end = 0.0
        for (step, seconds) in seconds.enumerated() {
            end += seconds
            if phase < end - 1e-9 { return step }
        }
        // A rounding residue at the loop seam belongs to the next loop's key frame.
        return 0
    }
}

enum SpriteClock { static let origin = Date(timeIntervalSinceReferenceDate: 0) }
