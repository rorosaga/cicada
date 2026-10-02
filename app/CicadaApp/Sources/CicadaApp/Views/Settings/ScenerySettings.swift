import SwiftUI

/// Settings → Sleep. Per-viewer scenery only; no action here starts work or fetches weather.
struct ScenerySettings: View {
    let mood: BookwormState
    let lampLit: Bool
    @AppStorage(SceneryMode.defaultsKey) private var sourceRaw = SceneryMode.localWeather.rawValue
    @AppStorage(ManualScenery.timeKey) private var timeRaw = "day"
    @AppStorage(ManualScenery.baseKey) private var baseRaw = "sunny"

    var body: some View {
        let mode = SceneryMode.stored(sourceRaw)
        let manual = ManualScenery(timeRaw: timeRaw, baseRaw: baseRaw)
        let scenery = Scenery.resolve(mode: mode, clock: SceneStore.shared.phase,
                                      forecast: LocalWeatherReader.shared.base(for: SceneStore.shared.timeZoneIdentifier),
                                      mood: mood, manual: manual)
        SettingsGroupCard(header: Copy.Scenery.group) {
            SettingsRow(.scenerySource, title: Copy.Scenery.source,
                        detail: mode == .localWeather ? Copy.Scenery.disclosure : nil) {
                Picker(Copy.Scenery.source, selection: Binding(get: { mode.rawValue }, set: { value in
                    var transaction = Transaction(animation: nil)
                    transaction.disablesAnimations = true
                    withTransaction(transaction) { sourceRaw = value }
                })) {
                    ForEach(SceneryMode.allCases) { Text($0.label).tag($0.rawValue) }
                }
                .pickerStyle(.menu)
                .labelsHidden()
            }
            if mode == .choose {
                SettingsDivider()
                SettingsRow(.sceneryTime, title: Copy.Scenery.time, control: { EmptyView() }) {
                    LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(SkyPhase.allCases, id: \.tag) { time in
                            SceneryTile(title: time.title, voice: "\(Copy.Scenery.time), \(time.title)",
                                        base: manual.base, time: time, selected: time == manual.time) {
                                timeRaw = time.tag
                            }
                        }
                    }
                }
                SettingsDivider()
                SettingsRow(.sceneryWeather, title: Copy.Scenery.weather, control: { EmptyView() }) {
                    LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(WindowWeather.all) { base in
                            SceneryTile(title: base.title, voice: "\(Copy.Scenery.weather), \(base.title)",
                                        base: base, time: manual.time, selected: base == manual.base) {
                                baseRaw = base.rawValue
                            }
                        }
                    }
                }
            }
            SettingsDivider()
            SettingsRow(.sceneryPreview, title: Copy.Scenery.preview, detail: scenery.text,
                        control: { EmptyView() }) {
                SceneryRoomArt(lampLit: lampLit, scenery: scenery, cell: 1) {
                    BookwormView(state: mood, latticeCell: 1, lighting: scenery.lighting, lampLit: lampLit)
                }
            }
        }
    }

    private var columns: [GridItem] { [.init(.adaptive(minimum: CicadaTheme.scaled(88)), spacing: CicadaTheme.spacingSM)] }
}

/// Native keyboard activation and focus; selection is a ground plus a text/VoiceOver twin, never hue alone.
private struct SceneryTile: View {
    let title, voice: String
    let base: WindowWeather
    let time: SkyPhase
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false
    var body: some View {
        Button {
            // Keyboard actions never animate (DR-65); choosing scenery is instant for either input method.
            var transaction = Transaction(animation: nil)
            transaction.disablesAnimations = true
            withTransaction(transaction, action)
        } label: {
            VStack(spacing: CicadaTheme.spacingXS) {
                WeatherThumbnail(base: base, time: time, cell: max(1, CicadaTheme.uiScale.rounded()))
                Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity)
            .background(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus),
                        in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay {
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .strokeBorder(selected ? CicadaTheme.textPrimary : CicadaTheme.border, lineWidth: 1)
            }
            .contentShape(Rectangle())
        }
        // Keep this selection row still, including the pressed state; the shared press style scales its label.
        .buttonStyle(.plain)
        .focusable()
        .onHover { hovering = $0 }
        .help(voice)
        .accessibilityLabel(voice)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
