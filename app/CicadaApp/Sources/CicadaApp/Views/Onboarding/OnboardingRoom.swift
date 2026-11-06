import SwiftUI

/// Onboarding's one illustration (owner 2026-10-16: "In onboarding maybe doing bookworm pixel room in detail would be
/// better, no?"): the study room the Sleep page draws, in detail — the same backdrop, window, lamp, plant, clock and
/// worm, at a WHOLE number of points per lattice cell, so no pixel is ever resampled (ruling R3, TODO ruling 18). It
/// replaced the painted meadow, which is retired everywhere.
///
/// Art only: no word and no number sits on it (DR-13), and nothing in it is a control — the Sleep page's hotspots,
/// pile and drop target stay there. The room's scenery follows the person's own choice (Settings → Sleep → The
/// scenery) from what is already known — a cached forecast, never a fetch from here. The worm's mood follows the
/// step (`OnboardingPage.roomMood`), so the room says what the page is about without a word.
struct OnboardingRoom: View {
    let mood: BookwormState
    /// Points per lattice cell (`OnboardingRoomLayout.cell`).
    let cell: CGFloat
    /// The working pages' pane (ROR-118, round 2): the room as a close view that fills the whole pane, its floor on the
    /// window's bottom edge and its wall carried up to the top edge, so no ground shows above or below it. Nil is the
    /// whole room at its own size (Welcome, Done).
    var fill: CGSize? = nil

    @AppStorage(SceneryMode.defaultsKey) private var sceneryRaw = SceneryMode.localWeather.rawValue
    @AppStorage(ManualScenery.timeKey) private var timeRaw = "day"
    @AppStorage(ManualScenery.baseKey) private var baseRaw = "sunny"

    var body: some View {
        let scenery = Scenery.resolve(mode: SceneryMode.stored(sceneryRaw), clock: SceneStore.shared.phase,
                                      forecast: LocalWeatherReader.shared.base(for: SceneStore.shared.timeZoneIdentifier),
                                      mood: mood, manual: ManualScenery(timeRaw: timeRaw, baseRaw: baseRaw))
        let size = deskSceneLayout(pixelScale: cell).size
        let art = SceneryRoomArt(lampLit: false, scenery: scenery, cell: cell) {
            BookwormView(state: mood, latticeCell: cell, lighting: scenery.lighting, lampLit: false)
        }
        // A hard bottom edge, as on the Sleep page: no fade (owner 2026-11-03).
        .frame(width: size.width, height: size.height)
        Group {
            if let fill {
                ZStack(alignment: .bottomLeading) {
                    // The wall above the room is the room's own top row, drawn tall: whole cells, never resampled
                    // into a different picture (its top rows hold no prop, so only wall and trim repeat).
                    DeskSceneView(lampLit: false, scenery: scenery, pixelScale: cell)
                        .frame(width: size.width, height: cell, alignment: .top)
                        .clipped()
                        .scaleEffect(x: 1, y: max(1, (fill.height - size.height) / cell + 2), anchor: .bottom)
                        .offset(y: cell - size.height)
                    art
                }
                .offset(x: -CGFloat(OnboardingRoomLayout.cropStartCol) * cell)
                .frame(width: fill.width, height: fill.height, alignment: .bottomLeading)
                .clipped()
            } else {
                art
            }
        }
        .accessibilityHidden(true)
    }
}

/// The room's geometry in onboarding, pure (`OnboardingRoomTests`).
enum OnboardingRoomLayout {
    /// Gap between the room and the Welcome / You're set card.
    static let cardGap: CGFloat = 24

    /// The largest whole number of points per cell that fits `width`, between 1 and `maxCell`. Never fractional, so
    /// a resize steps the room rather than blurring it.
    static func cell(fitting width: CGFloat, maxCell: CGFloat) -> CGFloat {
        guard width > 0 else { return 1 }
        return max(1, min(maxCell, (width / CGFloat(RoomLattice.cols)).rounded(.down)))
    }

    /// The pane shows the room's columns `cropStartCol ..< cropStartCol + cropCols` — most of the window, the plant,
    /// the worm whole on its beanbag with room to spare on its left (round 3: the head and glasses no longer sit on
    /// the edge), the clock and the mug, with a margin before the seam.
    static let cropStartCol = 27
    static let cropCols = 83
    /// Points per cell in the pane at 1×; scales with the UI scale and steps down, whole, before the column would
    /// drop below its minimum.
    static let paneCellAt1x: CGFloat = 8

    /// The working pages' pane cell: always whole points; 0 when the pane would be a sliver and goes (art only,
    /// DR-13).
    static func paneCell(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        guard w > 0, scale > 0 else { return 0 }
        let ideal = (paneCellAt1x * scale).rounded()
        let fits = ((w - OnboardingLayout.minColumn * scale) / CGFloat(cropCols)).rounded(.down)
        let cell = min(ideal, fits)
        return cell * CGFloat(cropCols) < OnboardingLayout.minPane * scale ? 0 : cell
    }

    static func paneWidth(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        paneCell(windowWidth: w, scale: scale) * CGFloat(cropCols)
    }

    /// Welcome: the room over its card, 960 × 384 over the 960 pt card (ROR-118 round 3).
    static func heroCell(cardWidth: CGFloat) -> CGFloat {
        cell(fitting: cardWidth, maxCell: 6)
    }
}
