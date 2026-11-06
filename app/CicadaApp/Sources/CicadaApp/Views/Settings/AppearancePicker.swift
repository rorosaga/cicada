import AppKit
import SwiftUI

/// How an appearance switch moves (owner 2026-10-26; DR-60, DR-61, DR-66): a pointer's choice cross-fades the whole
/// window on `CicadaMotion.settle`; a key press — or an assistive press — switches in one frame; Reduce Motion never
/// animates. `CicadaApp.applyAppearance` reads it at the moment the choice lands.
enum AppearanceMotion {
    static func animation(eventType: NSEvent.EventType?, reduceMotion: Bool) -> Animation? {
        if eventType == .keyDown || eventType == .keyUp { return nil }
        return CicadaMotion.settle(reduceMotion: reduceMotion)
    }

    @MainActor
    static func current() -> Animation? {
        animation(eventType: NSApp.currentEvent?.type,
                  reduceMotion: NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
    }
}

/// Settings → General → Appearance (owner 2026-10-26: "Keep it inside Settings with a preview of how the appearance
/// would change. Light, dark, or system; the default is system."). Three tiles, each a miniature of the app in that
/// appearance — the rail, a sidebar of rows, a page with a card — drawn from the two palettes' own tokens, never the
/// mode on screen; System is the two halves side by side, Light on the left. A tile is one button; the chosen one wears
/// the accent ring (DR-5's selection ring, as an option row's, DR-42) and its label in `textPrimary`. ← / → move the
/// choice from the keyboard, in one frame (DR-60). The sidebar's sun/moon toggle retired into this (§9 2026-10-26).
struct AppearancePicker: View {
    @Binding var selection: AppearancePreference

    var body: some View {
        // Round 1 (ROR-118): three larger tiles spread across the card, one cell each, so the choice leads the page.
        HStack(spacing: CicadaTheme.scaled(12)) {
            ForEach(AppearancePreference.pickerOrder) { choice in
                AppearanceTile(choice: choice, selected: selection == choice) { selection = choice }
                    .frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.appearance)
        .onKeyPress(.leftArrow) { step(-1) }
        .onKeyPress(.rightArrow) { step(1) }
    }

    private func step(_ by: Int) -> KeyPress.Result {
        selection = AppearancePreference.stepped(selection, by: by)
        return .handled
    }
}

private struct AppearanceTile: View {
    let choice: AppearancePreference
    let selected: Bool
    let choose: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: choose) {
            VStack(spacing: CicadaTheme.scaled(6)) {
                AppearanceMiniature(choice: choice, k: AppearanceMiniature.pickerScale)
                    .frame(width: AppearanceMiniature.width * AppearanceMiniature.pickerScale,
                           height: AppearanceMiniature.height * AppearanceMiniature.pickerScale)
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .overlay {
                        CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                            .strokeBorder(selected ? CicadaTheme.accent
                                          : CicadaTheme.ring(hovering ? .strong : .resting),
                                          lineWidth: selected ? 1.5 : 1)
                    }
                Text(choice.label)
                    .font(selected ? CicadaTheme.metaMediumFont : CicadaTheme.metaFont)
                    .foregroundStyle(selected || hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .help(choice.help)
        .accessibilityLabel(choice.label)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// A miniature of the app in one appearance: the rail, a sidebar with one selected row, and a page with a heading, text
/// lines and a ringed card. Every colour is the named palette's token (`CicadaTheme.Light` / `.Dark`), so the preview is
/// what that appearance paints — whatever the window shows now.
struct AppearanceMiniature: View {
    let choice: AppearancePreference
    /// Every measure below is multiplied by `k`, so a tile can be larger without a transform (DR-63).
    var k: CGFloat = 1
    static let width: CGFloat = 132
    static let height: CGFloat = 84
    /// Round 1 (ROR-118): the Settings picker draws them 1.3 times the size.
    static let pickerScale: CGFloat = 1.3

    var body: some View {
        switch choice {
        case .light: Pane(palette: .light, k: k)
        case .dark: Pane(palette: .dark, k: k)
        case .system:
            HStack(spacing: 0) {
                Pane(palette: .light, k: k).frame(width: Self.width * k / 2, alignment: .leading).clipped()
                Pane(palette: .dark, k: k).frame(width: Self.width * k / 2, alignment: .trailing).clipped()
            }
        }
    }

    private struct Pane: View {
        let palette: AppearancePalette
        let k: CGFloat

        var body: some View {
            HStack(spacing: 0) {
                // The rail: a column of glyph dots.
                VStack(spacing: 5 * k) {
                    ForEach(0..<5, id: \.self) { i in
                        Circle().fill(i == 1 ? palette.text.opacity(0.85) : palette.faint.opacity(0.6))
                            .frame(width: 4 * k, height: 4 * k)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.top, 10 * k)
                .frame(width: 14 * k)
                .frame(maxHeight: .infinity)
                .background(palette.rail)
                // The page: a heading, lines, and a ringed card with a selected row.
                VStack(alignment: .leading, spacing: 5 * k) {
                    CicadaTheme.shape(1.5 * k).fill(palette.text.opacity(0.9)).frame(width: 42 * k, height: 5 * k)
                    CicadaTheme.shape(k).fill(palette.faint.opacity(0.7)).frame(width: 70 * k, height: 3 * k)
                    VStack(alignment: .leading, spacing: 4 * k) {
                        HStack(spacing: 4 * k) {
                            Circle().fill(palette.accent).frame(width: 4 * k, height: 4 * k)
                            CicadaTheme.shape(k).fill(palette.text.opacity(0.8)).frame(width: 46 * k, height: 3 * k)
                        }
                        .padding(.horizontal, 4 * k)
                        .frame(maxWidth: .infinity, minHeight: 9 * k, alignment: .leading)
                        .background(CicadaTheme.shape(2 * k).fill(palette.selected))
                        CicadaTheme.shape(k).fill(palette.faint.opacity(0.6)).frame(width: 60 * k, height: 3 * k)
                            .padding(.horizontal, 4 * k)
                        CicadaTheme.shape(k).fill(palette.faint.opacity(0.6)).frame(width: 38 * k, height: 3 * k)
                            .padding(.horizontal, 4 * k)
                    }
                    .padding(.vertical, 5 * k)
                    .background(CicadaTheme.shape(3 * k).fill(palette.pane))
                    .overlay(CicadaTheme.shape(3 * k).strokeBorder(palette.ring, lineWidth: 1))
                    Spacer(minLength: 0)
                }
                .padding(8 * k)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(palette.base)
            }
            .frame(width: AppearanceMiniature.width * k, height: AppearanceMiniature.height * k)
            .accessibilityHidden(true)
        }
    }
}
