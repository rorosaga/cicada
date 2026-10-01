import Foundation
import SwiftUI

enum SpritePlaybackProfile: Equatable, Sendable {
    case full, gentle, still
    static func of(reduceMotion: Bool, lowPower: Bool) -> Self { reduceMotion ? .still : (lowPower ? .gentle : .full) }
    var slowdown: Double { self == .gentle ? CicadaMotion.spriteGentleSlowdown : 1 }
}

/// The union of the visible clips' frame boundaries, never a fixed frame rate.
struct SpriteFrameSchedule: TimelineSchedule {
    struct Track: Equatable { let origin: Date; let seconds: [TimeInterval]; let loops: Bool }
    let tracks: [Track]

    static func nextBoundary(after date: Date, track: Track) -> Date? {
        let total = track.seconds.reduce(0, +)
        let elapsed = date.timeIntervalSince(track.origin)
        guard total.isFinite, total > 0, elapsed.isFinite,
              track.seconds.allSatisfy({ $0.isFinite && $0 > 0 }) else { return nil }
        let cycle = track.loops ? floor(elapsed / total) : 0
        let phase = elapsed - cycle * total
        var end = 0.0
        for seconds in track.seconds {
            end += seconds
            if end > phase + 1e-9 { return track.origin.addingTimeInterval(cycle * total + end + 0.0005) }
        }
        return track.loops ? track.origin.addingTimeInterval((cycle + 1) * total + track.seconds[0] + 0.0005) : nil
    }

    func entries(from startDate: Date, mode: TimelineScheduleMode) -> AnyIterator<Date> {
        var first = true
        var cursor = startDate
        return AnyIterator {
            if first { first = false; return startDate }
            let next = tracks.compactMap { Self.nextBoundary(after: cursor, track: $0) }.min()
            guard let next else { return nil }
            // Consume all boundaries within one millisecond together.
            cursor = next.addingTimeInterval(0.001)
            return next
        }
    }
}
