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
        // The floor fades into the ground over its last five cells, as on the Sleep page (a mask, never a shadow).
        .mask { RoomFloorFade(height: size.height, fade: RoomFloorFade.fade(cell: cell)) }
        .frame(width: size.width, height: size.height)
        .accessibilityHidden(true)
    }
}

/// The room's geometry in onboarding, pure (`OnboardingRoomTests`).
enum OnboardingRoomLayout {
    /// Space kept clear on each side of the room inside the pane.
    static let paneMargin: CGFloat = 24
    /// Gap between the room and the Welcome / You're set card.
    static let cardGap: CGFloat = 24

    /// The largest whole number of points per cell that fits `width`, between 1 and `maxCell`. Never fractional, so
    /// a resize steps the room rather than blurring it.
    static func cell(fitting width: CGFloat, maxCell: CGFloat) -> CGFloat {
        guard width > 0 else { return 1 }
        return max(1, min(maxCell, (width / CGFloat(RoomLattice.cols)).rounded(.down)))
    }

    /// The working pages' pane: the room centred in it, up to 3 pt per cell (480 × 192 in the 540 pt pane).
    static func paneCell(paneWidth: CGFloat) -> CGFloat {
        cell(fitting: paneWidth - 2 * paneMargin, maxCell: 3)
    }

    /// Welcome and You're set: the room above the card, as wide as the card allows, up to 4 pt per cell (640 × 256
    /// over the 640 pt card).
    static func cardCell(cardWidth: CGFloat) -> CGFloat {
        cell(fitting: cardWidth, maxCell: 4)
    }
}
