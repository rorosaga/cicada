import SwiftUI

/// Animated state art: the loop shows the mood already true. Still refused: a flash, a clock, a count.
enum WindowWeather: String, CaseIterable, Identifiable, Equatable {
    case night, dawn, clear, fair, overcast, storm, curtains

    var id: String { rawValue }

    /// The legend's order.
    static let all: [WindowWeather] = [.night, .dawn, .clear, .fair, .overcast, .storm, .curtains]

    var title: String {
        switch self {
        case .night: "Night"
        case .dawn: "Dawn"
        case .clear: "Sunny"
        case .fair: "Partly cloudy"
        case .overcast: "Windy"
        case .storm: "Rainy"
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
        case .curtains: "Waiting to hear how Sleep is doing."
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

    /// A weather's key frame is the legend's still text twin.
    private func thumbnail(_ weather: WindowWeather) -> some View {
        let sheet = SpriteSheets.sheet(named: "room-weather")
        let frame = sheet?.clip(weather.rawValue)?.order.first
        let cell = max(1, CicadaTheme.uiScale.rounded())
        return Group {
            if let frame, let cg = sheet?.frameImage(frame) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        }
        .frame(width: 36 * cell, height: 32 * cell)
        .accessibilityHidden(true)
    }
}
