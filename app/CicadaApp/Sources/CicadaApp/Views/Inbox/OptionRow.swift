import SwiftUI

/// DR-42 — one answer, one tap: a radio (1.5 pt `textTertiary` ring, a 6 pt accent dot when
/// highlighted), the label (14 medium), its description (12 `textTertiary` — the server's words, age
/// first, G60), "Recommended" (`accentText`, `textPrimary` on the hover fill, DR-6), the age as a
/// `Tag`, ⏎ on the highlighted row and the row's number (DR-49). At rest `bgOption` with a resting
/// ring; hover one step up; highlighted a 1.5 pt accent ring (DR-5 use 3). A click answers at once.
struct OptionRow: View {
    let option: InboxOption
    /// R-DL5 — the label as shown: an id the graph holds reads as its page's name. `nil` shows `option.label`.
    var label: String? = nil
    private var shownLabel: String { label ?? option.label }
    /// 1…9; nil past the ninth row.
    let number: Int?
    let highlighted: Bool
    let onHover: () -> Void
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static var hoverFill: Color { CicadaTheme.mode == .dark ? CicadaTheme.bgButton : CicadaTheme.bgHover }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingMD) {
                RadioMark(on: highlighted)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(1)) {
                    Text(shownLabel)
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let description = option.description, !description.isEmpty {
                        Text(description)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if option.recommended {
                    Text(Copy.Inbox.recommended)
                        .font(CicadaTheme.metaMediumFont)
                        .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.accentText)
                }
                if let age = option.ageCapsule { Tag(text: age) }
                if highlighted { KeyHint("⏎") }
                if let number { KeyHint(String(number)) }
            }
            .padding(.leading, CicadaTheme.scaled(14))
            .padding(.trailing, CicadaTheme.scaled(12))
            .frame(height: CicadaTheme.scaled(RowMetrics.option))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? Self.hoverFill : CicadaTheme.bgOption))
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(highlighted ? CicadaTheme.accent : CicadaTheme.ring(.resting), lineWidth: highlighted ? 1.5 : 1))
        }
        .buttonStyle(.cicadaPlain)
        .help(option.description ?? shownLabel)
        .onHover { hovering = $0; if $0 { onHover() } }
        .accessibilityLabel(option.recommended ? "\(shownLabel), \(Copy.Inbox.recommended.lowercased())" : shownLabel)
        .accessibilityHint(number.map(Copy.Inbox.pressKey) ?? "")
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// The option row's radio (DR-42): drawn, so the ring is exactly 1.5 pt at every zoom.
struct RadioMark: View {
    let on: Bool
    var body: some View {
        Circle()
            .strokeBorder(on ? CicadaTheme.accent : CicadaTheme.textTertiary, lineWidth: 1.5)
            .frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
            .overlay {
                if on {
                    Circle().fill(CicadaTheme.accent)
                        .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                }
            }
            .accessibilityHidden(true)
    }
}

/// DR-8 / DR-3 / R-DI18 — a kind's hue appears once, as this outline glyph, which carries the kind's
/// name for the pointer and VoiceOver (light merge measures 2.98:1 and never stands alone).
struct KindGlyph: View {
    let kind: InboxKind
    var body: some View {
        Image(systemName: kind.icon)
            .font(CicadaTheme.icon(.list))
            .foregroundStyle(kind.color)
            .help(kind.label)
            .accessibilityLabel(kind.label)
    }
}
