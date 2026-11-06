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

    @AppStorage(SceneryMode.defaultsKey) private var sceneryRaw = SceneryMode.localWeather.rawValue
    @AppStorage(ManualScenery.timeKey) private var timeRaw = "day"
    @AppStorage(ManualScenery.baseKey) private var baseRaw = "sunny"

    var body: some View {
        let scenery = Scenery.resolve(mode: SceneryMode.stored(sceneryRaw), clock: SceneStore.shared.phase,
                                      forecast: LocalWeatherReader.shared.base(for: SceneStore.shared.timeZoneIdentifier),
                                      mood: mood, manual: ManualScenery(timeRaw: timeRaw, baseRaw: baseRaw))
        let size = deskSceneLayout(pixelScale: cell).size
        SceneryRoomArt(lampLit: false, scenery: scenery, cell: cell) {
            BookwormView(state: mood, latticeCell: cell, lighting: scenery.lighting, lampLit: false)
        }
        // A hard bottom edge, as on the Sleep page: no fade (owner 2026-11-03).
        .frame(width: size.width, height: size.height)
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

    /// The working pages' pane: the room edge to edge, centred on the window's height (640 × 256 in the 640 pt pane,
    /// `OnboardingLayout.paneWidth` always a whole number of cells).
    static func paneCell(paneWidth: CGFloat) -> CGFloat {
        cell(fitting: paneWidth, maxCell: 6)
    }

    /// Welcome: the room over its card, 800 × 320 over the 800 pt card (ROR-118).
    static func heroCell(cardWidth: CGFloat) -> CGFloat {
        cell(fitting: cardWidth, maxCell: 5)
    }
}
