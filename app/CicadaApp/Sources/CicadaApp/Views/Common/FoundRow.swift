import SwiftUI

/// Track I T4 (design §3.8, §7) — one "found on this Mac" row. One component,
/// many hosts: the `+` sheet's On this Mac strip (Task 8), and in part b the
/// Welcome checklist and Home's Getting started. The row renders; it decides
/// nothing — what is on (`LocalInventory`), what would run (`GET /agents/wiring`),
/// what its button does (the host). A dense row: `surfaceHover` fill, never a
/// lift (R9 §3.2); its mark nods through `markHover`.
enum FoundMark: Equatable {
    case logo(String)
    case app(bundleId: String, logo: String?, symbol: String)
}

enum FoundRowState: Equatable {
    case off, on
    case working(String)
    case needsAction(String)
    case failed(String)
}

struct FoundRow: View {
    let mark: FoundMark
    let title: String
    let detail: String
    let state: FoundRowState
    var disclosure: [String] = []
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    /// Instead of a button: the one thing to do is in Settings (a plain closure
    /// cannot reliably open that window — see `SettingsSectionLink`).
    var settingsLink: SettingsSection? = nil
    /// The Welcome's tick (W4, R-IB12): present, the tick IS the consent, so an
    /// `.off` row shows no Turn on — nothing runs before Start. Only Allow…
    /// (`.needsAction`) and Retry (`.failed`) keep a button. nil everywhere
    /// else (the `+` strip, Getting started), which keep their buttons.
    var tick: Binding<Bool>? = nil

    @State private var hovering = false
    @State private var expanded = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static func stateText(_ state: FoundRowState) -> String {
        switch state {
        case .off: Copy.foundOff
        case .on: Copy.foundOn
        case .working(let text), .needsAction(let text), .failed(let text): text
        }
    }

    static func accessibilityLabel(title: String, detail: String, state: FoundRowState) -> String {
        "\(title). \(detail). \(stateText(state))"
    }

    /// W4 — a ticked row reads its tick, not its machine state: before Start
    /// nothing is on, so "On." means "Start will turn this on".
    static func tickLabel(title: String, detail: String, ticked: Bool) -> String {
        "\(title). \(detail). \(ticked ? Copy.foundOn : Copy.foundOff)."
    }

    static func defaultActionTitle(_ state: FoundRowState) -> String? {
        switch state {
        case .off: Copy.foundTurnOn
        case .failed: Copy.foundRetry
        case .needsAction(let label): label
        case .on, .working: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let tick {
                    Toggle(isOn: tick) { EmptyView() }
                        .toggleStyle(FoundTickStyle())
                        .labelsHidden()
                }
                markView.markHover(hovering: hovering)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                    Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    if case .failed(let why) = state {
                        Text(why).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                trailing
                if !disclosure.isEmpty {
                    Button { expanded.toggle() } label: {
                        Image(systemName: "chevron.right").rotationEffect(.degrees(expanded ? 90 : 0))
                    }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityLabel("\(Copy.foundWhatThisChanges), \(title)")
                }
            }
            if expanded {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(disclosure, id: \.self) { line in
                        Text(line).font(CicadaTheme.font(size: 11, design: .monospaced))
                            .foregroundStyle(CicadaTheme.textSecondary).textSelection(.enabled)
                    }
                }
                .padding(.leading, CicadaTheme.scaled(32))
                .transition(.opacity)
            }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .background(hovering ? CicadaTheme.surfaceHover : .clear,
                    in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .animation(CicadaMotion.settle(reduceMotion: reduceMotion), value: expanded)
        .onHover { hovering = $0 }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(tick.map { Self.tickLabel(title: title, detail: detail, ticked: $0.wrappedValue) }
                            ?? Self.accessibilityLabel(title: title, detail: detail, state: state))
    }

    @ViewBuilder private var markView: some View {
        let size = CicadaTheme.scaled(24)
        switch mark {
        case .logo(let name):
            LogoImage.platformTile(name: name, size: size, systemFallback: "app")
        case .app(let bundleId, let logo, let symbol):
            LogoImage.platformTile(name: logo ?? "", bundleId: bundleId, size: size, systemFallback: symbol)
        }
    }

    @ViewBuilder private var trailing: some View {
        switch state {
        case .on:
            Label(Copy.foundOn, systemImage: "checkmark.circle.fill")
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.success)
        case .working(let text):
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        case .off where tick != nil:
            // The tick is the consent (W4): no Turn on before Start.
            EmptyView()
        case .off, .needsAction, .failed:
            if let settingsLink {
                SettingsSectionLink(section: settingsLink, label: actionTitle ?? Copy.foundClaudeDesktopDetail)
            } else if let title = actionTitle ?? Self.defaultActionTitle(state), let action {
                Button(title, action: action).buttonStyle(.bordered)
            }
        }
    }
}

/// W4 — the tick: `checkmark.circle.fill` in the accent (a UI state, never a
/// nature token — R-M2 keeps meadow for washes and the one pill), a bounce on
/// change that Reduce Motion removes.
struct FoundTickStyle: ToggleStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            Image(systemName: configuration.isOn ? "checkmark.circle.fill" : "circle")
                .font(CicadaTheme.font(size: 16))
                .foregroundStyle(configuration.isOn ? CicadaTheme.accent : CicadaTheme.textTertiary)
                .symbolEffect(.bounce, value: configuration.isOn)
                .symbolEffectsRemoved(reduceMotion)
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(configuration.isOn ? .isSelected : [])
    }
}
