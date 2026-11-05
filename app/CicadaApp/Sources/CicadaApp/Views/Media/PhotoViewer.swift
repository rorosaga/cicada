import AppKit
import SwiftUI

/// ROR-117 — a photo in the viewer sheet. Fit to the pane; pinch, the buttons or a double click zoom, and a zoomed
/// photo scrolls. Nothing animates (a zoom is the person's own act, DR-60) and nothing is fetched: the file is read
/// from where this Mac holds it. DR-9: no border or shadow of its own.
struct PhotoViewer: View {
    let image: NSImage

    @State private var zoom: CGFloat = 1
    @State private var committed: CGFloat = 1

    static let range: ClosedRange<CGFloat> = 1...6

    var body: some View {
        GeometryReader { geo in
            ScrollView([.horizontal, .vertical]) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: geo.size.width * zoom, height: geo.size.height * zoom)
                    .onTapGesture(count: 2) { set(zoom > 1 ? 1 : 2) }
            }
            .gesture(MagnificationGesture()
                .onChanged { zoom = Self.clamp(committed * $0) }
                .onEnded { _ in committed = zoom })
        }
        .background(CicadaTheme.bgPane)
        .overlay(alignment: .bottomTrailing) {
            HStack(spacing: CicadaTheme.spacingXS) {
                IconButton(systemName: "minus.magnifyingglass", help: Copy.mediaZoomOut) { set(zoom / 1.5) }
                IconButton(systemName: "plus.magnifyingglass", help: Copy.mediaZoomIn) { set(zoom * 1.5) }
            }
            .padding(CicadaTheme.spacingMD)
        }
    }

    private func set(_ value: CGFloat) {
        zoom = Self.clamp(value)
        committed = zoom
    }

    static func clamp(_ value: CGFloat) -> CGFloat { min(range.upperBound, max(range.lowerBound, value)) }
}
