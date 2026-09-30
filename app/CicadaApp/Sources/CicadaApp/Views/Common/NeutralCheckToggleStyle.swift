import SwiftUI

/// G162 (P8, DESIGN_RULES §9 2026-09-30) — the picker's check: a `textPrimary` tick on `bgSelected` inside a
/// `textSecondary` ring, never the accent (DR-5 gives the accent six uses and selection is not one of them). A
/// `ToggleStyle`, so VoiceOver keeps the checkbox's semantics. The existing native `.checkbox` uses stay as they are.
struct NeutralCheckToggleStyle: ToggleStyle {
    static let size: CGFloat = 16

    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                ZStack {
                    CicadaTheme.shape(CicadaTheme.radiusXS)
                        .fill(configuration.isOn ? CicadaTheme.bgSelected : Color.clear)
                    CicadaTheme.shape(CicadaTheme.radiusXS)
                        .strokeBorder(CicadaTheme.textSecondary, lineWidth: 1)
                    if configuration.isOn {
                        Image(systemName: "checkmark")
                            .font(CicadaTheme.font(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textPrimary)
                    }
                }
                .frame(width: CicadaTheme.scaled(Self.size), height: CicadaTheme.scaled(Self.size))
                configuration.label
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityRepresentation { Toggle(isOn: configuration.$isOn) { configuration.label } }
    }
}
