import Foundation
import CoreGraphics

enum BookwormArtSet: Equatable { case room, small }

/// Sheet registry: the state and response matrix remain the authority for tag names.
enum BookwormArt {
    static let roomFrame = CGSize(width: 64, height: 48)
    static let smallFrame = CGSize(width: 18, height: 18)
    static let covers = 3
    static let states: [BookwormState] = [.awake, .reading, .sleeping(stage: 1), .digesting, .happy,
                                         .hungry, .error, .curious(count: 1)]

    static func sheetName(_ state: BookwormState, _ set: BookwormArtSet,
                          lighting: RoomLighting = .day, lampLit: Bool = false) -> String {
        set == .small ? "bookworm-small" : "bookworm-\(state.caseName)\(lighting.suffix(lampLit: lampLit))"
    }

    static func tag(_ look: BookwormLook, cover: Int = 1) -> String {
        let base = look.keySegment ?? "idle"
        return cover == 1 ? base : "\(base)@\(cover)"
    }

    static func requiredTags(_ state: BookwormState) -> Set<String> {
        let base = BookwormLook.reachable(for: state).map { tag($0) }
        var names = Set(base)
        if case .reading = state {
            for k in 2...covers { names.formUnion(base.map { "\($0)@\(k)" }) }
        }
        if case .sleeping = state { names.formUnion(["intro", "outro"]) }
        return names
    }

    static func smallRequiredTags() -> Set<String> { Set(states.map(\.caseName)) }

    /// Exact cover, base look, idle, then the sheet's first frame. Missing sheets remain missing.
    static func fallbackClip(in sheet: SpriteSheet, tag: String) -> SpriteClip? {
        if let clip = sheet.clip(tag) { return clip }
        if let base = tag.split(separator: "@").first, let clip = sheet.clip(String(base)) { return clip }
        if let clip = sheet.clip("idle") { return clip }
        guard let seconds = sheet.frameSeconds.first else { return nil }
        return SpriteClip(sheet: sheet.name, tag: "frame0", order: [0], seconds: [seconds])
    }

    static func clip(_ state: BookwormState, look: BookwormLook, cover: Int = 1,
                     set: BookwormArtSet = .room, lighting: RoomLighting = .day,
                     lampLit: Bool = false) -> (SpriteSheet, SpriteClip)? {
        guard let sheet = SpriteSheets.sheet(named: sheetName(state, set, lighting: lighting, lampLit: lampLit)) else { return nil }
        let name = set == .small ? state.caseName : tag(look, cover: state.caseName == "reading" ? cover : 1)
        guard let clip = fallbackClip(in: sheet, tag: name) else { return nil }
        return (sheet, clip)
    }

    static func coverIndex(at date: Date, profile: SpritePlaybackProfile) -> Int {
        guard profile != .still, let total = SpriteSheets.sheet(named: "bookworm-reading")?.clip("idle")?.total,
              total > 0 else { return 1 }
        let elapsed = max(0, date.timeIntervalSince(SpriteClock.origin))
        guard elapsed.isFinite else { return 1 }
        let cycle = floor(elapsed / (total * profile.slowdown) + 1e-9)
        return 1 + Int(cycle.truncatingRemainder(dividingBy: Double(covers)))
    }

    static func beatLength(_ kind: BookwormReaction, state: BookwormState) -> TimeInterval {
        let look = BookwormLook.reaction(kind, .center)
        return SpriteSheets.sheet(named: sheetName(state, .room))?.clip(tag(look))?.total ?? CicadaMotion.spriteBeatMax
    }

    static func transitionClip(_ t: BookwormTransition, lighting: RoomLighting = .day,
                               lampLit: Bool = false) -> (SpriteSheet, SpriteClip)? {
        let name = sheetName(.sleeping(stage: 1), .room, lighting: lighting, lampLit: lampLit)
        guard let sheet = SpriteSheets.sheet(named: name), let clip = sheet.clip(t.rawValue) else { return nil }
        return (sheet, clip)
    }

    static func transitionLength(_ t: BookwormTransition) -> TimeInterval {
        transitionClip(t)?.1.total ?? CicadaMotion.spriteTransitionMax
    }

    /// Cache the union once. Before art lands, the declared canvas is the honest layout bound.
    static let wormInk: CGRect = {
        let rects = states.filter { $0.caseName != "curious" }.compactMap {
            SpriteSheets.sheet(named: sheetName($0, .room))?.slices["ink"]
        }
        return rects.isEmpty ? CGRect(origin: .zero, size: roomFrame) : rects.reduce(CGRect.null) { $0.union($1) }
    }()

    static let eyePixel: CGPoint = {
        guard let eye = SpriteSheets.sheet(named: "bookworm-awake")?.slices["eye"] else {
            return CGPoint(x: roomFrame.width / 2, y: roomFrame.height / 2)
        }
        return CGPoint(x: eye.midX, y: eye.midY)
    }()
}

struct BookwormSize: Equatable {
    let set: BookwormArtSet
    let pixelScale: CGFloat
    let size: CGSize

    static func resolve(pointSize: CGFloat, uiScale: CGFloat, latticeCell: CGFloat?) -> BookwormSize {
        let set: BookwormArtSet = latticeCell != nil || pointSize >= 48 ? .room : .small
        let canvas = set == .room ? BookwormArt.roomFrame : BookwormArt.smallFrame
        let k = latticeCell ?? max(1, (pointSize * uiScale / canvas.height).rounded())
        return BookwormSize(set: set, pixelScale: k, size: CGSize(width: canvas.width * k, height: canvas.height * k))
    }
}

enum BookwormTransition: String, Equatable { case yawn = "intro", stretch = "outro" }
struct ActiveTransition: Equatable {
    let kind: BookwormTransition
    let startedAt: Date
    let id: UUID
    let length: TimeInterval
}
