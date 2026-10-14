import SwiftUI

struct PillOption<Value: Hashable>: Hashable {
    let value: Value
    let label: String
}

/// Capsule segments — the Claude-style segmented control (design §1.3). The
/// pills are buttons for looks; VoiceOver and `macos-harness` get a real
/// `Picker` through `.accessibilityRepresentation`, so the control keeps
/// picker semantics (one value, a selected option).
///
/// Owner 2026-10-14 (Home review #4) — the control "read as plain text": its track was `surfaceHover` on a `bgFocus`
/// card (the same lightness) and the selected pill `surfaceElevated` (= `bgFocus`) with an opaque `border` stroke. Now
/// the track is recessed `bgPane` and the selected pill `bgSelected`, each with a resting ring (DR-9: a ring, never a
/// border), the selected label 12 medium (DR-16 reserves semibold), and the control 28 pt tall (DR-69).
struct PillPicker<Value: Hashable>: View {
    /// 2 pt of track around a 24 pt pill: 28 pt, a compact button's height (DR-33).
    static var pillHeight: CGFloat { 24 }
    static var trackInset: CGFloat { 2 }
    static var height: CGFloat { pillHeight + 2 * trackInset }

    let title: String
    @Binding var selection: Value
    let options: [PillOption<Value>]
    /// F-09 — a card's picker: 6 pt of horizontal padding so four scene pills fit a narrow card (R-HO15).
    var compact = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(2)) {
            ForEach(options, id: \.self) { option in
                let selected = option.value == selection
                Button { selection = option.value } label: {
                    Text(option.label)
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .padding(.horizontal, compact ? CicadaTheme.scaled(6) : CicadaTheme.spacingMD)
                        .frame(height: CicadaTheme.scaled(Self.pillHeight))
                        .background(Capsule().fill(selected ? CicadaTheme.bgSelected : Color.clear))
                        .overlay { if selected { Capsule().strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1) } }
                        .contentShape(Capsule())
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(CicadaTheme.scaled(Self.trackInset))
        .background(Capsule().fill(CicadaTheme.bgPane))
        .ringed(in: Capsule())
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: selection)
        .accessibilityRepresentation {
            Picker(title, selection: $selection) {
                ForEach(options, id: \.self) { Text($0.label).tag($0.value) }
            }
        }
    }
}
