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
                    // The wall above the room is the room's own top nine rows, repeated upward (ROR-118 round 5; round 4
                    // stretched row one, a blank wall): the backdrop's wallpaper repeats every nine rows, so whole bands
                    // of it carry its dashes and light up the wall, whole cells, never resampled. The backdrop alone,
                    // so no prop's top edge repeats with it.
                    wallBands(scenery: scenery, height: fill.height - size.height, roomHeight: size.height)
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

extension OnboardingRoom {
    /// The wall's repeat, in lattice rows: the backdrop's dashes sit every nine rows from the top.
    static let wallPeriodRows = 9

    /// Bands of the backdrop's top `wallPeriodRows` rows, stacked so their bottom edge meets the room's top edge and
    /// they cover `height`, bottom-leading like the room.
    @ViewBuilder
    func wallBands(scenery: Scenery, height: CGFloat, roomHeight: CGFloat) -> some View {
        let band = CGFloat(Self.wallPeriodRows) * cell
        let count = max(1, Int((max(0, height) / band).rounded(.up)) + 1)
        let art = RoomArt.tag(.backdrop, lampLit: false, scenery: scenery)
        let sheet = art.flatMap { SpriteSheets.sheet(named: $0.sheet) }
        VStack(spacing: 0) {
            ForEach(0..<count, id: \.self) { _ in
                SpriteLayerView(clip: art.flatMap { sheet?.clip($0.tag) }, sheet: sheet, pixelScale: cell,
                                canvasSize: CGSize(width: DeskScene.cols, height: DeskScene.rows))
                    .frame(width: CGFloat(DeskScene.cols) * cell, height: band, alignment: .top)
                    .clipped()
            }
        }
        .offset(y: -roomHeight)
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

    /// The pane shows the room's columns `cropStartCol ..< cropStartCol + cropCols` — round 4: every prop whole, the lamp,
    /// the window, the plant, the worm on its beanbag, the clock and the mug, with a margin each side, so no object
    /// is cut by the pane's edge on any step (round 3 cut the window, plant and lamp).
    static let cropStartCol = 0
    static let cropCols = 112
    /// Points per cell in the pane at 1×: 5 is a 560 pt pane, 39% of a 1440 pt window, the column the rest. It scales
    /// with the UI scale and steps down, whole, before the column would drop below its minimum.
    static let paneCellAt1x: CGFloat = 5

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
