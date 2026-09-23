import SwiftUI

struct PillOption<Value: Hashable>: Hashable {
    let value: Value
    let label: String
}

/// Capsule segments — the Claude-style segmented control (design §1.3). The
/// pills are buttons for looks; VoiceOver and `macos-harness` get a real
/// `Picker` through `.accessibilityRepresentation`, so the control keeps
/// picker semantics (one value, a selected option).
struct PillPicker<Value: Hashable>: View {
    let title: String
    @Binding var selection: Value
    let options: [PillOption<Value>]
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(2)) {
            ForEach(options, id: \.self) { option in
                let selected = option.value == selection
                Button { selection = option.value } label: {
                    Text(option.label)
                        .font(CicadaTheme.font(size: 12, weight: selected ? .semibold : .regular))
                        .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .padding(.vertical, CicadaTheme.scaled(5))
                        .background(Capsule().fill(selected ? CicadaTheme.surfaceElevated : Color.clear))
                        .overlay(Capsule().stroke(selected ? CicadaTheme.border : Color.clear, lineWidth: 1))
                }
                .buttonStyle(.cicadaPlain)
            }
        }
        .padding(CicadaTheme.scaled(2))
        .background(Capsule().fill(CicadaTheme.surfaceHover))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: selection)
        .accessibilityRepresentation {
            Picker(title, selection: $selection) {
                ForEach(options, id: \.self) { Text($0.label).tag($0.value) }
            }
        }
    }
}
