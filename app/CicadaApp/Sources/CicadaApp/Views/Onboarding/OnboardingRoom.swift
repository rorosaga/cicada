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
    /// The working pages' pane (ROR-118, round 6): the room cropped a little top and bottom and centred in the pane,
    /// the page's plain ground above and below. Nil is the whole room at its own size (Welcome, Done).
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
                // Round 6 (owner 2026-11-06: the drawn floor and ceiling "look super weird"): the original room art only,
                // a few rows cropped off its top and bottom so no wall repeats, whole cells, centred in the pane on the
                // page's own dark ground. No wall bands, no floor, nothing added.
                art
                    .offset(x: -CGFloat(OnboardingRoomLayout.cropStartCol) * cell,
                            y: -CGFloat(OnboardingRoomLayout.cropTopRows) * cell)
                    .frame(width: CGFloat(OnboardingRoomLayout.cropCols) * cell,
                           height: CGFloat(OnboardingRoomLayout.cropRows) * cell, alignment: .topLeading)
                    .clipped()
                    .frame(width: fill.width, height: fill.height, alignment: .center)
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

    /// Rows cropped off the room's top and bottom in the pane: 2 above the window's frame, 2 of the baseboard's foot;
    /// the worm (rows 9–57 from the bottom), window, lamp, plant, clock and mug stay whole.
    static let cropTopRows = 2
    static let cropRows = 60

    /// Welcome: the room over its card, 960 × 384 over the 960 pt card (ROR-118 round 3).
    static func heroCell(cardWidth: CGFloat) -> CGFloat {
        cell(fitting: cardWidth, maxCell: 6)
    }
}
