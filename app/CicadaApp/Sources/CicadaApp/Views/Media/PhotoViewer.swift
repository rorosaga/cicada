import AppKit
import SwiftUI

/// ROR-117 / ROR-131 — a photo in the viewer sheet and in the lightbox (one zoomable surface, not two). Fit to the
/// pane; pinch, the buttons, a double click or the keys (+ − 0) zoom, and a zoomed photo scrolls. The zoom reads as a
/// percentage of the fit, with a button back to it. Nothing animates (a zoom is the person's own act, DR-60) and
/// nothing is fetched: the file is read from where this Mac holds it. DR-9: no border or shadow of its own.
struct PhotoViewer: View {
    let image: NSImage
    /// The lightbox draws it on its dark scrim; the sheet and the page on the pane.
    var background: Color = CicadaTheme.bgPane
    var onDark = false

    @State private var zoom: CGFloat = 1
    @State private var committed: CGFloat = 1

    static let range: ClosedRange<CGFloat> = 1...6
    static let step: CGFloat = 1.5

    var body: some View {
        GeometryReader { geo in
            ScrollView([.horizontal, .vertical]) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: geo.size.width * zoom, height: geo.size.height * zoom)
                    .onTapGesture(count: 2) { set(zoom > 1 ? 1 : 2) }
            }
            .scrollIndicators(zoom > 1 ? .automatic : .hidden)
            .gesture(MagnificationGesture()
                .onChanged { zoom = Self.clamp(committed * $0) }
                .onEnded { _ in committed = zoom })
        }
        .background(background)
        .overlay(alignment: .bottomTrailing) { controls }
        .focusable()
        .focusEffectDisabled()
        .onKeyPress(characters: CharacterSet(charactersIn: "+=-_0")) { press in
            guard let next = Self.zoom(after: press.characters, from: zoom) else { return .ignored }
            set(next)
            return .handled
        }
        .accessibilityLabel(Copy.mediaZoomLevel(Self.percent(zoom)))
    }

    private var controls: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(Self.percent(zoom))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(onDark ? Color.white.opacity(0.8) : CicadaTheme.textTertiary)
                .monospacedDigit()
                .padding(.trailing, CicadaTheme.spacingXS)
            button("arrow.down.right.and.arrow.up.left", Copy.mediaFit, enabled: zoom > 1) { set(1) }
            button("minus.magnifyingglass", Copy.mediaZoomOut, enabled: zoom > Self.range.lowerBound) { set(zoom / Self.step) }
            button("plus.magnifyingglass", Copy.mediaZoomIn, enabled: zoom < Self.range.upperBound) { set(zoom * Self.step) }
        }
        .padding(CicadaTheme.spacingMD)
    }

    @ViewBuilder
    private func button(_ symbol: String, _ help: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        if onDark {
            Button(action: action) {
                Image(systemName: symbol)
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(Color.white.opacity(enabled ? 0.9 : 0.35))
                    .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .disabled(!enabled)
            .help(help)
            .accessibilityLabel(help)
        } else {
            IconButton(systemName: symbol, help: help, action: action)
                .disabled(!enabled)
        }
    }

    private func set(_ value: CGFloat) {
        zoom = Self.clamp(value)
        committed = zoom
    }

    static func clamp(_ value: CGFloat) -> CGFloat { min(range.upperBound, max(range.lowerBound, value)) }

    /// What a typed character does to the zoom: + or = in, − out, 0 back to the fit; nil for any other.
    static func zoom(after characters: String, from zoom: CGFloat) -> CGFloat? {
        switch characters {
        case "+", "=": clamp(zoom * step)
        case "-", "_": clamp(zoom / step)
        case "0": 1
        default: nil
        }
    }

    /// `100%` is the fit.
    static func percent(_ zoom: CGFloat) -> String { "\(Int((zoom * 100).rounded()))%" }
}
