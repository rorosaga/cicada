import SwiftUI

/// The window's sky (Track Z R-Z11): STATE art. A total function of the mood
/// and nothing else — no count, no clock, no stage number — so the window can
/// never say something the sentence does not. The seven are listed once, in
/// `all`, and the legend (its text twin) is the only place their meanings are
/// written (P16). Refused: drift, a storm flash, and any weather driven by the
/// time of day (G125: state outranks the clock).
enum WindowWeather: String, CaseIterable, Identifiable, Equatable {
    case night, dawn, clear, fair, overcast, storm, curtains

    var id: String { rawValue }

    /// The legend's order.
    static let all: [WindowWeather] = [.night, .dawn, .clear, .fair, .overcast, .storm, .curtains]

    var title: String {
        switch self {
        case .night: "Night"
        case .dawn: "Dawn"
        case .clear: "Clear"
        case .fair: "Fair"
        case .overcast: "Overcast"
        case .storm: "Storm"
        case .curtains: "Curtains drawn"
        }
    }

    var meaning: String {
        switch self {
        case .night: "A cycle is running."
        case .dawn: "A cycle just finished."
        case .clear: "Caught up. Nothing waiting."
        case .fair: "Things are waiting to be read."
        case .overcast: "Overdue: it's been a while."
        case .storm: "The last cycle failed."
        case .curtains: "No reading yet."
        }
    }
}

/// `.curious` never reaches the Sleep page (G125 R2); it maps for totality.
func windowWeather(for mood: BookwormState) -> WindowWeather {
    switch mood {
    case .sleeping: .night
    case .digesting: .dawn
    case .happy: .clear
    case .reading, .curious: .fair
    case .hungry: .overcast
    case .error: .storm
    case .awake: .curtains
    }
}

/// The window's legend (I11): the seven skies with their thumbnails, the
/// current one marked in words for VoiceOver and by a ground for the eye.
struct WindowLegend: View {
    let current: WindowWeather

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.windowLegendHeader)
                .font(CicadaTheme.captionFont.italic())
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(WindowWeather.all) { weather in
                HStack(spacing: CicadaTheme.spacingSM) {
                    thumbnail(weather)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(weather.title)
                            .font(CicadaTheme.font(size: 12, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(weather.meaning)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    Spacer(minLength: 0)
                }
                .padding(CicadaTheme.spacingXS)
                .background(weather == current ? CicadaTheme.surfaceHover : Color.clear,
                            in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(weather == current ? .isSelected : [])
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 320, alignment: .leading)
        .background(CicadaTheme.surface)
    }

    /// Drawn from the same scene cache as the room (P13), on its own 16-cell
    /// grid so it is a smaller GRID, never a smaller rendering (P12's rule).
    private func thumbnail(_ weather: WindowWeather) -> some View {
        let pt = PixelRenderer.snappedPointSize(32 * CicadaTheme.uiScale, gridSize: 16)
        return Image(nsImage: PixelRenderer.cachedImage(
            key: "desk.paneThumb|\(weather.rawValue)|\(Int(pt))",
            grid: DeskSceneSprites.paneThumbnail(weather), gridSize: 16, pointSize: pt, palette: DeskPalette.ns))
            .interpolation(.none)
            .frame(width: pt, height: pt)
            .accessibilityHidden(true)
    }
}
