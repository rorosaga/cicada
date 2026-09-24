import SwiftUI

/// The one in-page search field (G136 S5; round-3 design §1.3, §3.7). Graph,
/// Clusters, the Feed and a source's conversations all use it, so
/// the keys are learned once: Esc clears and a second Esc leaves the field;
/// ↑/↓ reach the page's result list when it has one; ⏎ submits. A 28 pt
/// capsule — magnifier, prompt, a clear button when there is text, a "⌘F"
/// hint when it is empty and idle.
///
/// ⌘F arrives through the `pageFind` menu command (A6), published only while
/// `findEnabled` — the graph's field sits under every other tab (R-SU10) —
/// and never while the ⌘K palette is up (R-SU9).
struct CicadaSearchField: View {
    enum Style {
        /// Content layer (R9 §2.7): a hover fill and a hairline, never glass.
        case content
        /// Floating over the graph, in the material its other controls use —
        /// Liquid Glass over the canvas waits on the G109 frame-time check
        /// (`LiquidGlass.swift`; plan R-SU17).
        case overCanvas
    }

    enum EscapeAction: Equatable { case clear, blur }

    @Binding var text: String
    let prompt: String
    var style: Style = .content
    var findEnabled = true
    var width: CGFloat? = nil
    var onSubmit: () -> Void = {}
    var onMove: ((Int) -> Void)? = nil
    var onFocusChange: (Bool) -> Void = { _ in }
    /// R-DS21 — a field inside a modal hands Esc to the modal's close instead of clearing, then
    /// blurring, itself. The Settings panel's search field is the one caller: this field answers
    /// Esc with `.handled`, and whether AppKit gives the key to it or to the panel's
    /// `.cancelAction` first is not something a test can observe, so the field defers.
    var onEscape: (() -> Void)? = nil
    /// `autofocus` — a field that exists only because ⌘F opened it takes the focus as it appears (the
    /// Graph's find overlay, R-DG5).
    var autofocus = false

    @FocusState private var focused: Bool
    @Environment(FindPaletteModel.self) private var palette: FindPaletteModel?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "magnifyingglass")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            TextField(prompt, text: $text)
                .textFieldStyle(.plain)
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($focused)
                .onSubmit(onSubmit)
                .onKeyPress(.downArrow) { move(1) }
                .onKeyPress(.upArrow) { move(-1) }
                .onKeyPress(.escape) {
                    if let onEscape { onEscape(); return .handled }
                    switch Self.escape(textIsEmpty: text.isEmpty) {
                    case .clear: text = ""
                    case .blur: focused = false
                    }
                    return .handled
                }
                .accessibilityLabel(prompt)
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").font(CicadaTheme.font(size: 11))
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityLabel("Clear search")
            } else if Self.showsFindHint(text: text, focused: focused) {
                Text("⌘F")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help("Find on this page (⌘F)")
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(width: width, height: CicadaTheme.scaled(28))
        .modifier(SearchFieldChrome(style: style))
        .onChange(of: focused) { _, now in onFocusChange(now) }
        .task { if autofocus { focused = true } }
        .publishesPageFind(enabled: findEnabled && !(palette?.isPresented ?? false)) { focused = true }
    }

    private func move(_ delta: Int) -> KeyPress.Result {
        guard let onMove else { return .ignored }
        onMove(delta)
        return .handled
    }

    static func escape(textIsEmpty: Bool) -> EscapeAction { textIsEmpty ? .blur : .clear }
    static func showsFindHint(text: String, focused: Bool) -> Bool { text.isEmpty && !focused }
}

private struct SearchFieldChrome: ViewModifier {
    let style: CicadaSearchField.Style

    @ViewBuilder
    func body(content: Content) -> some View {
        switch style {
        case .content:
            content
                .background(Capsule().fill(CicadaTheme.surfaceHover))
                .overlay(Capsule().stroke(CicadaTheme.border, lineWidth: 1))
        case .overCanvas:
            content.glassCard(cornerRadius: CicadaTheme.scaled(14))
        }
    }
}
