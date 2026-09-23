import AppKit
import XCTest
@testable import CicadaApp

/// Track Z §7.3 / Z-P13 — the window as frame + pane, checked against the REAL
/// worm: the sun, moon, stars and bolt are fully visible beside the worm's
/// union ink over every frame, pose and reaction of the moods that show that
/// weather, and never under a mullion; every cloud is at least half visible.
final class WindowSpritesTests: XCTestCase {

    private struct Cell: Hashable { let r: Int; let c: Int }

    private var paneLayer: DeskLayer { DeskScene.plan.first { $0.prop == .pane }! }
    private var frameLayer: DeskLayer { DeskScene.plan.first { $0.prop == .window }! }

    /// Pane cells the frame paints over (jambs, mullions, sill), in pane space.
    private var frameCells: Set<Cell> {
        let dx = frameLayer.cellX - paneLayer.cellX, dy = paneLayer.cellY - frameLayer.cellY
        var out = Set<Cell>()
        for (r, row) in DeskSceneSprites.window.enumerated() {
            for (c, ch) in row.enumerated() where ch != "." { out.insert(Cell(r: r + dy, c: c + dx)) }
        }
        return out
    }

    /// The worm's union ink, in pane space, over every look of every page mood
    /// that shows `weather` (per weather — Z-P13).
    private func wormMask(for weather: WindowWeather) -> Set<Cell> {
        let moods: [BookwormState] = [.awake, .happy, .reading, .hungry, .digesting, .error] + (1...5).map { .sleeping(stage: $0) }
        let dx = DeskScene.wormCell.x - paneLayer.cellX, dy = paneLayer.cellY - DeskScene.wormCell.y
        var mask = Set<Cell>()
        for mood in moods where windowWeather(for: mood) == weather {
            for look in BookwormLook.reachable(for: mood) {
                for frame in BookwormSprites.frames(for: mood, look: look).frames {
                    for (r, row) in frame.enumerated() {
                        for (c, ch) in row.enumerated() where ch != "." { mask.insert(Cell(r: r + dy, c: c + dx)) }
                    }
                }
            }
        }
        return mask
    }

    /// What must be fully visible, and which characters make a cloud (§7.3).
    private func classes(_ weather: WindowWeather) -> (full: Set<Character>, cloud: Set<Character>) {
        switch weather {
        case .night: (["m", "n", "s"], [])
        case .dawn, .clear: (["m", "n"], [])
        case .fair: (["m", "n"], ["j", "x"])
        case .overcast: ([], ["j", "N"])
        case .storm: (["s"], ["N", "x"])
        case .curtains: ([], [])
        }
    }

    private func cells(_ weather: WindowWeather, _ chars: Set<Character>) -> Set<Cell> {
        var out = Set<Cell>()
        for (r, row) in DeskSceneSprites.pane(weather).enumerated() {
            for (c, ch) in row.enumerated() where chars.contains(ch) { out.insert(Cell(r: r, c: c)) }
        }
        return out
    }

    /// 4-connected groups — one per cloud.
    private func clouds(_ all: Set<Cell>) -> [Set<Cell>] {
        var left = all, groups: [Set<Cell>] = []
        while let seed = left.first {
            left.remove(seed)
            var group: Set<Cell> = [seed], frontier = [seed]
            while let cell = frontier.popLast() {
                for next in [Cell(r: cell.r + 1, c: cell.c), Cell(r: cell.r - 1, c: cell.c),
                             Cell(r: cell.r, c: cell.c + 1), Cell(r: cell.r, c: cell.c - 1)] where left.contains(next) {
                    left.remove(next); group.insert(next); frontier.append(next)
                }
            }
            groups.append(group)
        }
        return groups
    }

    func test_theFeaturesAreFullyVisible_andEveryCloudAtLeastHalf() {
        for weather in WindowWeather.all {
            let hidden = wormMask(for: weather).union(frameCells)
            let (full, cloud) = classes(weather)
            for cell in cells(weather, full) {
                XCTAssertFalse(hidden.contains(cell), "\(weather) \(cell) is hidden")
            }
            for group in clouds(cells(weather, cloud)) {
                let visible = group.subtracting(hidden).count
                XCTAssertGreaterThanOrEqual(visible * 2, group.count, "\(weather) cloud \(visible)/\(group.count)")
            }
        }
    }

    /// Design defect 8: two of the old window's four stars sat behind the worm.
    func test_theNightKeepsFourStars() {
        XCTAssertEqual(cells(.night, ["s"]).count, 4)
    }

    func test_everyPaneIsGlassOnly_flushToColumnZero_inTheDeskPalette() {
        let glass = DeskSceneSprites.windowGlass
        let allowed = Set(DeskPalette.colors.keys).union(["."])
        for weather in WindowWeather.all {
            let pane = DeskSceneSprites.pane(weather)
            XCTAssertEqual(pane.count, 24)
            XCTAssertEqual(DeskSceneSprites.inkBounds(pane)?.rows, glass.rows, "\(weather)")
            XCTAssertEqual(DeskSceneSprites.inkBounds(pane)?.cols, 0...(glass.cols.count - 1), "\(weather)")
            for row in pane {
                XCTAssertEqual(row.count, 24)
                for ch in row where !allowed.contains(ch) { XCTFail("\(weather): '\(ch)'") }
            }
        }
        XCTAssertEqual(Set(WindowWeather.all.map { DeskSceneSprites.pane($0) }).count, 7, "seven different skies")
    }

    /// The frame is today's window with the glass taken out: jambs and
    /// mullions in `f`, the sill in `d`, nothing else.
    func test_theFrameHasNoGlass() {
        let frame = DeskSceneSprites.window
        let glass = DeskSceneSprites.windowGlass
        for r in glass.rows {
            for c in glass.cols {
                let mullion = (9...10).contains(c) || (11...12).contains(r)
                XCTAssertEqual(Array(frame[r])[c], mullion ? "f" : ".", "(\(r),\(c))")
            }
        }
        XCTAssertEqual(frame[22], String(repeating: "d", count: 20) + "....")
    }

    /// Opt-in art check (design §14 Z8):
    /// `CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests`
    /// writes one PNG per weather — frame over pane, with the first frame of
    /// that weather's mood at its real offset — for a person to look at.
    func test_writeCompositesWhenAsked() throws {
        guard ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1" else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-composites")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let moodFor: [WindowWeather: BookwormState] = [.night: .sleeping(stage: 2), .dawn: .digesting, .clear: .happy,
                                                        .fair: .reading, .overcast: .hungry, .storm: .error, .curtains: .awake]
        let palette = DeskPalette.ns.merging(PixelRenderer.nsColors(BookwormPalette.colors)) { desk, _ in desk }
        for weather in WindowWeather.all {
            var grid = Array(repeating: Array(repeating: Character("."), count: 36), count: 36)
            func paint(_ layer: PixelGrid, at dx: Int) {
                for (r, row) in layer.enumerated() {
                    for (c, ch) in row.enumerated() where ch != "." && c + dx < 36 { grid[r][c + dx] = ch }
                }
            }
            paint(DeskSceneSprites.pane(weather), at: 2)
            paint(DeskSceneSprites.window, at: 0)
            paint(BookwormSprites.frames(for: moodFor[weather]!).frames[0], at: 10)
            let image = PixelRenderer.image(grid: grid.map { String($0) }, gridSize: 36, pointSize: 360, palette: palette)
            let rep = NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation))
            try XCTUnwrap(rep?.representation(using: .png, properties: [:]))
                .write(to: dir.appendingPathComponent("\(weather.rawValue).png"))
        }
    }
}
