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
        HStack(spacing: CicadaTheme.scaled(14)) {
            ForEach(AppearancePreference.pickerOrder) { choice in
                AppearanceTile(choice: choice, selected: selection == choice) { selection = choice }
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
                AppearanceMiniature(choice: choice)
                    .frame(width: AppearanceMiniature.width, height: AppearanceMiniature.height)
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
    static let width: CGFloat = 132
    static let height: CGFloat = 84

    var body: some View {
        switch choice {
        case .light: Pane(palette: .light)
        case .dark: Pane(palette: .dark)
        case .system:
            HStack(spacing: 0) {
                Pane(palette: .light).frame(width: Self.width / 2, alignment: .leading).clipped()
                Pane(palette: .dark).frame(width: Self.width / 2, alignment: .trailing).clipped()
            }
        }
    }

    private struct Pane: View {
        let palette: AppearancePalette

        var body: some View {
            HStack(spacing: 0) {
                // The rail: a column of glyph dots.
                VStack(spacing: 5) {
                    ForEach(0..<5, id: \.self) { i in
                        Circle().fill(i == 1 ? palette.text.opacity(0.85) : palette.faint.opacity(0.6))
                            .frame(width: 4, height: 4)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.top, 10)
                .frame(width: 14)
                .frame(maxHeight: .infinity)
                .background(palette.rail)
                // The page: a heading, lines, and a ringed card with a selected row.
                VStack(alignment: .leading, spacing: 5) {
                    CicadaTheme.shape(1.5).fill(palette.text.opacity(0.9)).frame(width: 42, height: 5)
                    CicadaTheme.shape(1).fill(palette.faint.opacity(0.7)).frame(width: 70, height: 3)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 4) {
                            Circle().fill(palette.accent).frame(width: 4, height: 4)
                            CicadaTheme.shape(1).fill(palette.text.opacity(0.8)).frame(width: 46, height: 3)
                        }
                        .padding(.horizontal, 4)
                        .frame(maxWidth: .infinity, minHeight: 9, alignment: .leading)
                        .background(CicadaTheme.shape(2).fill(palette.selected))
                        CicadaTheme.shape(1).fill(palette.faint.opacity(0.6)).frame(width: 60, height: 3)
                            .padding(.horizontal, 4)
                        CicadaTheme.shape(1).fill(palette.faint.opacity(0.6)).frame(width: 38, height: 3)
                            .padding(.horizontal, 4)
                    }
                    .padding(.vertical, 5)
                    .background(CicadaTheme.shape(3).fill(palette.pane))
                    .overlay(CicadaTheme.shape(3).strokeBorder(palette.ring, lineWidth: 1))
                    Spacer(minLength: 0)
                }
                .padding(8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(palette.base)
            }
            .frame(width: AppearanceMiniature.width, height: AppearanceMiniature.height)
            .accessibilityHidden(true)
        }
    }
}
