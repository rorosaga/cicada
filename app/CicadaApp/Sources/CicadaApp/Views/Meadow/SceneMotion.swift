import CoreGraphics
import Foundation
import SwiftUI

/// C10 (R-HO3) — every number the living painting moves by, as pure functions of the clock, so a test holds the
/// amplitudes, the pauses and "gentler, never frozen" (DR-66) without rendering a frame, and a live look that wants a
/// slower cloud changes one token in `CicadaMotion`.
enum SceneProfile: Equatable, Sendable {
    /// Every layer moves.
    case full
    /// Reduce Motion or Low Power (DR-66, R-HO7): nothing travels; the grass sways a third as far, stars and fireflies
    /// keep breathing, seeds fade in place.
    case gentle

    static func of(reduceMotion: Bool, lowPower: Bool) -> SceneProfile { reduceMotion || lowPower ? .gentle : .full }
}

/// R-HO7 — the frame budget and the pause rule, pure.
enum SceneRunPolicy {
    static func frameInterval(lowPower: Bool) -> TimeInterval {
        lowPower ? CicadaMotion.sceneLowPowerFrameInterval : CicadaMotion.sceneFrameInterval
    }

    /// A scene nobody can see spends no frames.
    static func isPaused(windowVisible: Bool, hostPaused: Bool) -> Bool { !windowVisible || hostPaused }
}

enum SceneGrassSide: CaseIterable, Sendable {
    case left, right

    var art: MeadowArt { self == .left ? .grassLeft : .grassRight }
    /// rationale-F: "rotating from its root corner" — the outer bottom corner.
    var pivot: UnitPoint { self == .left ? .bottomLeading : .bottomTrailing }
}

struct SceneCamera: Equatable {
    let scale: CGFloat
    let dx: CGFloat
    let dy: CGFloat
}

struct SceneCloud: Equatable {
    let lane: Int
    let art: MeadowArt
    let frame: CGRect
    let opacity: Double
}

struct SceneStar: Equatable, Sendable {
    let x: CGFloat, y: CGFloat, radius: CGFloat
    let period: TimeInterval, phase: Double
}

struct SceneFirefly: Equatable, Sendable {
    let x: CGFloat, y: CGFloat
    let wander: TimeInterval, glow: TimeInterval, phase: Double
}

struct SceneSeed: Equatable, Sendable {
    let x: CGFloat, y: CGFloat
    let drift: CGVector
    let crossing: TimeInterval, phase: Double
}

struct SceneParticle: Equatable {
    let center: CGPoint
    let radius: CGFloat
    let opacity: Double
    let tilt: Double
}

struct SceneLight: Equatable {
    /// In the painting's 0…1 space.
    let center: CGPoint
    /// A fraction of the painting's width.
    let radius: CGFloat
    let opacity: Double
}

enum SceneMotion {
    static func frac(_ x: Double) -> Double { x - x.rounded(.down) }

    /// R-HO5 — the camera breathes from the 1.01 floor up to 1.028 and drifts only within the breath above the floor.
    static func camera(at t: TimeInterval, container: CGSize, profile: SceneProfile) -> SceneCamera {
        let floor = CicadaMotion.sceneOverscan
        guard profile == .full else { return SceneCamera(scale: floor, dx: 0, dy: 0) }
        let angle = 2 * Double.pi * t / CicadaMotion.sceneCameraPeriod
        let scale = floor + (CicadaMotion.sceneCameraScale - floor) * CGFloat((1 - cos(angle)) / 2)
        let room = (scale - floor) / 2
        func clamp(_ v: CGFloat, _ limit: CGFloat) -> CGFloat { max(-limit, min(limit, v)) }
        return SceneCamera(scale: scale,
                           dx: clamp(CicadaMotion.sceneCameraDrift.width * CGFloat(sin(angle)), room * container.width),
                           dy: clamp(CicadaMotion.sceneCameraDrift.height * CGFloat(sin(angle / 2)), room * container.height))
    }

    /// Degrees; positive turns the clump clockwise about its roots.
    static func grassAngle(_ side: SceneGrassSide, at t: TimeInterval, profile: SceneProfile) -> Double {
        let amplitude = profile == .full ? CicadaMotion.sceneGrassAmplitude : CicadaMotion.sceneGrassGentleAmplitude
        let period = profile == .full
            ? (side == .left ? CicadaMotion.sceneGrassPeriodLeft : CicadaMotion.sceneGrassPeriodRight)
            : CicadaMotion.sceneGrassGentlePeriod
        let lag = side == .left ? 0 : CicadaMotion.sceneGrassLag
        return amplitude * sin(2 * .pi * (t - lag) / period)
    }

    /// R-HO10 — `MeadowRules`' opacities: the night clouds stay faint beside the moon (ART_DIRECTION §5).
    static func cloudOpacity(_ time: SceneTime) -> Double {
        time == .night ? MeadowRules.darkCloudOpacity : MeadowRules.lightCloudOpacity
    }

    /// One way, left to right, a whole crossing per lane; under `.gentle` each holds its resting place.
    static func clouds(at t: TimeInterval, plate: CGRect, container: CGSize, framing: SceneFraming,
                       time: SceneTime, profile: SceneProfile) -> [SceneCloud] {
        SceneLayout.lanes(for: framing, plate: plate).enumerated().map { index, lane in
            let height = lane.width * SceneLayout.cloudAspect
            let progress = profile == .full ? frac(t / lane.crossing + lane.phase) : lane.phase
            let x = -lane.width + CGFloat(progress) * (container.width + lane.width)
            return SceneCloud(lane: index, art: lane.art,
                              frame: CGRect(x: x, y: lane.centerY - height / 2, width: lane.width, height: height),
                              opacity: cloudOpacity(time))
        }
    }

    static func twinkle(_ star: SceneStar, at t: TimeInterval, profile: SceneProfile) -> Double {
        let period = profile == .full ? star.period : CicadaMotion.sceneStarGentlePeriod
        return 0.18 + 0.74 * (0.5 + 0.5 * sin(2 * .pi * t / period + star.phase))
    }

    static func firefly(_ f: SceneFirefly, at t: TimeInterval, plate: CGRect, profile: SceneProfile) -> SceneParticle {
        let home = CGPoint(x: plate.minX + f.x * plate.width, y: plate.minY + f.y * plate.height)
        let reach = profile == .full ? CicadaMotion.sceneFireflyReach : 0
        let dx = reach * CGFloat(sin(2 * .pi * t / f.wander + f.phase))
        let dy = reach * CGFloat(sin(2 * .pi * t / (f.wander * 1.3) + 2 * f.phase))
        let period = profile == .full ? f.glow : CicadaMotion.sceneFireflyGentleGlow
        let glow = 0.25 + 0.75 * (0.5 + 0.5 * sin(2 * .pi * t / period + f.phase))
        return SceneParticle(center: CGPoint(x: home.x + dx, y: home.y + dy), radius: 2.2, opacity: glow, tilt: 0)
    }

    /// A seed rises from its cluster along its drift, fading in and out; under `.gentle` it rests and fades in place.
    static func seed(_ s: SceneSeed, at t: TimeInterval, plate: CGRect, profile: SceneProfile) -> SceneParticle {
        let u = profile == .full ? frac(t / s.crossing + s.phase) : CicadaMotion.sceneSeedRestProgress
        let x = plate.minX + (s.x + s.drift.dx * CGFloat(u)) * plate.width
        let y = plate.minY + (s.y + s.drift.dy * CGFloat(u)) * plate.height
        guard profile == .full else {
            let pulse = 0.35 + 0.35 * (0.5 + 0.5 * sin(2 * .pi * t / CicadaMotion.sceneSeedGentlePulse + 2 * .pi * s.phase))
            return SceneParticle(center: CGPoint(x: x, y: y), radius: 2.4, opacity: pulse, tilt: 0)
        }
        let swing = sin(2 * .pi * t / CicadaMotion.sceneSeedBobPeriod + 2 * .pi * s.phase)
        let fade = min(u / 0.1, 1) * min((1 - u) / 0.15, 1)
        return SceneParticle(center: CGPoint(x: x + CicadaMotion.sceneSeedBob * CGFloat(swing), y: y), radius: 2.4,
                             opacity: 0.7 * fade, tilt: CicadaMotion.sceneSeedTilt * swing)
    }

    static func light(_ c: SceneComposition, time: SceneTime, at t: TimeInterval, profile: SceneProfile) -> SceneLight {
        let period = profile == .full
            ? (time == .night ? CicadaMotion.sceneLightNightPeriod : CicadaMotion.sceneLightDayPeriod)
            : CicadaMotion.sceneLightGentlePeriod
        let breath = 0.35 + 0.6 * (0.5 + 0.5 * sin(2 * .pi * t / period))
        return SceneLight(center: SceneLayout.lightCenter(c, time), radius: 0.45, opacity: CicadaMotion.sceneLightPeak * breath)
    }
}
