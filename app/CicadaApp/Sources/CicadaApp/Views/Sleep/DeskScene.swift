import SwiftUI

enum DeskProp: String, CaseIterable, Hashable { case backdrop, clock, pane, skyfx, window, plant, lamp, fly, beanbag, mug }

/// A canvas placed in cells at its bottom-left corner, in strictly ascending draw order.
struct DeskLayer: Equatable {
    let prop: DeskProp
    let cellX, cellY, w, h, z: Int
}

struct DeskSceneLayout: Equatable {
    let cell: CGFloat
    let size: CGSize
    let layers: [DeskLayer]
    let wormOrigin: CGPoint
    let pileFrame: CGRect
}

/// G176's floor plan; tested against the art run's room-plan.json.
enum DeskScene {
    static let cols = RoomLattice.cols
    static let rows = RoomLattice.rows
    static let plan: [DeskLayer] = [
        .init(prop: .backdrop, cellX: 0, cellY: 0, w: 110, h: 64, z: 0),
        .init(prop: .clock, cellX: 94, cellY: 34, w: 15, h: 15, z: 1),
        .init(prop: .pane, cellX: 20, cellY: 27, w: 36, h: 32, z: 2),
        .init(prop: .skyfx, cellX: 20, cellY: 27, w: 36, h: 32, z: 3),
        .init(prop: .window, cellX: 18, cellY: 23, w: 40, h: 38, z: 4),
        .init(prop: .plant, cellX: 21, cellY: 0, w: 12, h: 22, z: 5),
        .init(prop: .lamp, cellX: 0, cellY: 0, w: 18, h: 50, z: 6),
        .init(prop: .fly, cellX: 0, cellY: 32, w: 20, h: 26, z: 7),
        .init(prop: .beanbag, cellX: 36, cellY: 0, w: 62, h: 12, z: 8),
        .init(prop: .mug, cellX: 100, cellY: 0, w: 8, h: 9, z: 9),
    ]
    static let wormCell = (x: 36, y: 9)
    static let pileCell = (x: 110, y: 0, width: 50, height: 52)
}

func deskSceneLayout(uiScale: Double = CicadaTheme.uiScale, pixelScale: CGFloat? = nil) -> DeskSceneLayout {
    let cell = pixelScale ?? RoomLattice.cell(uiScale: uiScale)
    return DeskSceneLayout(cell: cell,
        size: CGSize(width: CGFloat(DeskScene.cols) * cell, height: CGFloat(DeskScene.rows) * cell),
        layers: DeskScene.plan,
        wormOrigin: CGPoint(x: CGFloat(DeskScene.wormCell.x) * cell, y: CGFloat(DeskScene.wormCell.y) * cell),
        pileFrame: CGRect(x: CGFloat(DeskScene.pileCell.x) * cell, y: CGFloat(DeskScene.pileCell.y) * cell,
                          width: CGFloat(DeskScene.pileCell.width) * cell, height: CGFloat(DeskScene.pileCell.height) * cell))
}

enum RoomArt {
    static func tag(_ prop: DeskProp, lampLit: Bool, scenery: Scenery) -> (sheet: String, tag: String)? {
        let night = scenery.lighting == .dark
        switch prop {
        case .backdrop, .lamp:
            return ("room-\(prop.rawValue)", (night ? "night-" : "") + (lampLit ? "lit" : "dark"))
        case .pane: return ("room-weather", scenery.weatherTag)
        case .skyfx: return scenery.overlayTag.map { ("room-skyfx", $0) }
        case .clock: return ("room-clock", night ? "face-night" : "face")
        case .fly: return lampLit ? ("room-fly", "buzz") : nil
        default: return ("room-\(prop.rawValue)", night ? "night-\(lampLit ? "lit" : "dark")" : "idle")
        }
    }
}

/// Inert sprite leaves on the lattice; the room art crossfades lighting with the pane.
struct DeskSceneView: View {
    var lampLit: Bool
    var scenery: Scenery
    var pixelScale: CGFloat? = nil

    var body: some View {
        let layout = deskSceneLayout(pixelScale: pixelScale)
        ZStack(alignment: .bottomLeading) {
            Color.clear
            ForEach(layout.layers, id: \.prop) { layer in
                if layer.prop != .clock, let art = RoomArt.tag(layer.prop, lampLit: lampLit, scenery: scenery) {
                    let sheet = SpriteSheets.sheet(named: art.sheet)
                    SpriteLayerView(clip: sheet?.clip(art.tag), sheet: sheet, pixelScale: layout.cell,
                                    canvasSize: CGSize(width: layer.w, height: layer.h))
                        .offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)
                }
            }
        }
        .frame(width: layout.size.width, height: layout.size.height, alignment: .bottomLeading)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Lighting, sky and worm switch as one art layer. Hotspots and the real pile remain stable siblings.
struct SceneryRoomArt<Worm: View>: View {
    let lampLit: Bool
    let scenery: Scenery
    let cell: CGFloat
    var includesClock = true
    @ViewBuilder var worm: () -> Worm
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var appearance: String { scenery.weatherTag + "|" + (scenery.overlayTag ?? "") + "|" + (lampLit ? "lit" : "dark") }

    var body: some View {
        let layout = deskSceneLayout(pixelScale: cell)
        ZStack(alignment: .bottomLeading) {
            ZStack(alignment: .bottomLeading) {
                DeskSceneView(lampLit: lampLit, scenery: scenery, pixelScale: cell)
                worm().offset(x: layout.wormOrigin.x, y: -layout.wormOrigin.y)
            }
            .id(appearance)
            .transition(.opacity)
            if includesClock, let clock = layout.layers.first(where: { $0.prop == .clock }) {
                RoomClock(lighting: scenery.lighting, cell: cell)
                    .offset(x: CGFloat(clock.cellX) * cell, y: -CGFloat(clock.cellY) * cell)
            }
        }
        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: appearance)
        .frame(width: layout.size.width, height: layout.size.height, alignment: .bottomLeading)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
