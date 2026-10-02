import SwiftUI

/// Base weather is environment art. A lightning flash remains refused.
enum WindowWeather: String, CaseIterable, Identifiable, Equatable {
    case sunny, cloudy, windy, rainy, curtains
    var id: String { rawValue }
    static let all = allCases
    var title: String {
        switch self { case .sunny: "Sunny"; case .cloudy: "Cloudy"; case .windy: "Windy"; case .rainy: "Rainy"; case .curtains: "Curtains drawn" }
    }
    var meaning: String {
        switch self {
        case .sunny: "Caught up. Nothing waiting."
        case .cloudy: "Things are waiting to be read."
        case .windy: "Overdue: it's been a while."
        case .rainy: "The last cycle failed."
        case .curtains: "Waiting to hear how Sleep is doing."
        }
    }
}

func windowWeather(for mood: BookwormState) -> WindowWeather {
    switch mood {
    case .sleeping, .digesting, .happy: .sunny
    case .reading, .curious: .cloudy
    case .hungry: .windy
    case .error: .rainy
    case .awake: .curtains
    }
}

/// Inert key frames shared by legend and Settings. Labels always sit beside/below the pixels.
struct WeatherThumbnail: View {
    let base: WindowWeather
    let time: SkyPhase
    var cell: CGFloat = 1
    var body: some View {
        let sheet = SpriteSheets.sheet(named: "room-weather")
        let frame = sheet?.clip("\(base.rawValue)-\(time.tag)")?.order.first
        Group {
            if let frame, let cg = sheet?.frameImage(frame) {
                Image(decorative: cg, scale: 1).resizable().interpolation(.none)
            } else { Color.clear }
        }
        .frame(width: 36 * cell, height: 32 * cell)
        .accessibilityHidden(true)
    }
}

struct WindowLegend: View {
    let current: Scenery
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(current.text)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Text(Copy.Scenery.legend)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if current.source == .sleep || current.source == .fallback {
                ForEach(WindowWeather.all) { weather in
                    HStack(spacing: CicadaTheme.spacingSM) {
                        WeatherThumbnail(base: weather, time: current.time)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(weather.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                            // Sunny is also the base under Sleep's moment layers; those never claim an empty queue.
                            Text(weather == current.base ? (current.overlay?.meaning ?? weather.meaning) : weather.meaning)
                                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(CicadaTheme.spacingXS)
                    .background(weather == current.base ? CicadaTheme.bgSelected : Color.clear,
                                in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(weather == current.base ? .isSelected : [])
                }
            }
            SettingsSectionLink(section: .sleep, row: .scenerySource, label: Copy.Scenery.change)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 320, alignment: .leading)
        .background(CicadaTheme.surface)
    }
}
