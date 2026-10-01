import SwiftUI

enum DeskProp: String, CaseIterable, Hashable { case backdrop, pane, window, plant, lamp, fly, beanbag, mug }

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
        .init(prop: .pane, cellX: 20, cellY: 27, w: 36, h: 32, z: 1),
        .init(prop: .window, cellX: 18, cellY: 23, w: 40, h: 38, z: 2),
        .init(prop: .plant, cellX: 21, cellY: 0, w: 12, h: 22, z: 3),
        .init(prop: .lamp, cellX: 0, cellY: 0, w: 18, h: 50, z: 4),
        .init(prop: .fly, cellX: 0, cellY: 32, w: 20, h: 26, z: 5),
        .init(prop: .beanbag, cellX: 36, cellY: 0, w: 62, h: 12, z: 6),
        .init(prop: .mug, cellX: 100, cellY: 0, w: 8, h: 9, z: 7),
    ]
    static let wormCell = (x: 36, y: 9)
    static let pileCell = (x: 110, y: 0, width: 50, height: 52)
}

func deskSceneLayout(uiScale: Double = CicadaTheme.uiScale) -> DeskSceneLayout {
    let cell = RoomLattice.cell(uiScale: uiScale)
    return DeskSceneLayout(cell: cell,
        size: CGSize(width: CGFloat(DeskScene.cols) * cell, height: CGFloat(DeskScene.rows) * cell),
        layers: DeskScene.plan,
        wormOrigin: CGPoint(x: CGFloat(DeskScene.wormCell.x) * cell, y: CGFloat(DeskScene.wormCell.y) * cell),
        pileFrame: CGRect(x: CGFloat(DeskScene.pileCell.x) * cell, y: CGFloat(DeskScene.pileCell.y) * cell,
                          width: CGFloat(DeskScene.pileCell.width) * cell, height: CGFloat(DeskScene.pileCell.height) * cell))
}

enum RoomArt {
    static func tag(_ prop: DeskProp, lampLit: Bool, weather: WindowWeather) -> (sheet: String, tag: String)? {
        switch prop {
        case .backdrop: ("room-backdrop", lampLit ? "lit" : "dark")
        case .lamp: ("room-lamp", lampLit ? "lit" : "dark")
        case .pane: ("room-weather", weather.rawValue)
        case .fly: lampLit ? ("room-fly", "buzz") : nil
        default: ("room-\(prop.rawValue)", "idle")
        }
    }
}

/// Inert sprite leaves on the lattice. Only the pane and fly tick; the pane retains its mood crossfade.
struct DeskSceneView: View {
    var lampLit: Bool
    var weather: WindowWeather = .night
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let layout = deskSceneLayout()
        ZStack(alignment: .bottomLeading) {
            Color.clear
            ForEach(layout.layers, id: \.prop) { layer in
                if let art = RoomArt.tag(layer.prop, lampLit: lampLit, weather: weather) {
                    let sheet = SpriteSheets.sheet(named: art.sheet)
                    if layer.prop == .pane {
                        ZStack {
                            SpriteLayerView(clip: sheet?.clip(art.tag), sheet: sheet, pixelScale: layout.cell,
                                            canvasSize: CGSize(width: layer.w, height: layer.h))
                                .id(weather)
                                .transition(.opacity)
                        }
                        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: weather)
                        .offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)
                    } else {
                        SpriteLayerView(clip: sheet?.clip(art.tag), sheet: sheet, pixelScale: layout.cell,
                                        canvasSize: CGSize(width: layer.w, height: layer.h))
                            .offset(x: CGFloat(layer.cellX) * layout.cell, y: -CGFloat(layer.cellY) * layout.cell)
                    }
                }
            }
        }
        .frame(width: layout.size.width, height: layout.size.height, alignment: .bottomLeading)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
