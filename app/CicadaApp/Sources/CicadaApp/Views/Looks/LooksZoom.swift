import AppKit
import SwiftUI

/// Looks polish (owner, 2026-10-15: "clicking the pic should expand the view smoothly, like an overlay") — the enlarged
/// screenshot. A click on a look's picture, in its grid tile or in the detail column, grows it from that thumbnail's
/// frame to fit the board (`CicadaMotion.morph`), over a scrim; a tall full-page shot fits the width and scrolls. Esc,
/// a click outside or × closes it, shrinking it back to the picture it came from. DR-60: the keyboard path (⌘Y, Space
/// on a focused picture, Esc) opens and closes in one frame; DR-66: under Reduce Motion it only fades
/// (`CicadaMotion.fade`). DR-9/10: the picture's depth is its ring, never a shadow.
///
/// Pure over its inputs: the state, the choice of motion and the fitted frame are tested (`LooksPolishTests`).
struct LooksZoom: Equatable {
    /// The coordinate space every frame here is in: the Looks board's.
    static let space = "looks.board"

    var refId: String?
    /// The thumbnail's frame the picture grows from and shrinks back to.
    var source: CGRect = .zero
    /// The geometry's target: false draws the picture at `source`, true at its fitted frame.
    var expanded = false

    var isPresented: Bool { refId != nil }

    enum Trigger: Equatable { case pointer, keyboard }
    /// How a change moves: not at all (the keyboard, DR-60), a short fade (Reduce Motion, DR-66), or the zoom.
    enum Style: Equatable { case instant, fade, zoom }

    static func style(_ trigger: Trigger, reduceMotion: Bool) -> Style {
        if trigger == .keyboard { return .instant }
        return reduceMotion ? .fade : .zoom
    }

    /// The trigger of the action running now: a key press is the keyboard, anything else the pointer.
    @MainActor
    static func currentTrigger() -> Trigger {
        trigger(for: NSApp.currentEvent?.type)
    }

    static func trigger(for type: NSEvent.EventType?) -> Trigger {
        type == .keyDown || type == .keyUp ? .keyboard : .pointer
    }

    /// Present `id` from `frame`. The zoom presents collapsed and then expands; every other style presents expanded.
    mutating func present(_ id: String, from frame: CGRect, style: Style) {
        refId = id
        source = frame
        expanded = style != .zoom
    }

    mutating func dismiss() {
        refId = nil
        expanded = false
    }

    /// Where the picture is drawn now: its source while collapsed, its fitted frame when expanded.
    func frame(fitted: CGRect) -> CGRect { expanded || source.isEmpty ? fitted : source }

    /// The frame the picture grows to in a board of `container`, and whether it scrolls: the whole picture fitted
    /// inside the margin, never larger than its own pixels; a tall full-page shot (fitting it whole would leave it
    /// under half the width) fits the width instead, as tall as the board, and scrolls.
    static func fitted(image: CGSize, in container: CGSize, margin: CGFloat) -> (frame: CGRect, scrolls: Bool) {
        let avail = CGSize(width: max(container.width - 2 * margin, 1), height: max(container.height - 2 * margin, 1))
        let size = image.width > 0 && image.height > 0 ? image : CGSize(width: 1600, height: 1000)
        let whole = min(avail.width / size.width, avail.height / size.height, 1)
        if size.width * whole < avail.width * 0.5, size.height > avail.height {
            let width = min(avail.width, size.width)
            let rect = CGRect(x: (container.width - width) / 2, y: margin, width: width, height: avail.height)
            return (rect, true)
        }
        let w = size.width * whole, h = size.height * whole
        return (CGRect(x: (container.width - w) / 2, y: (container.height - h) / 2, width: w, height: h), false)
    }
}

/// Where each picture a zoom can start from sits right now. A plain reference, not observed: a tile scrolling past
/// writes here without re-rendering the board; the zoom reads it only when it opens or closes.
final class LooksFrameBook {
    var tiles: [String: CGRect] = [:]
    var detail: (id: String, frame: CGRect)?

    /// The frame to grow from or shrink back to for `id`: the detail column's picture when it shows that look (the
    /// tile may have moved when the column opened), else its tile, else `fallback`.
    func frame(for id: String, fallback: CGRect) -> CGRect {
        if let detail, detail.id == id, !detail.frame.isEmpty { return detail.frame }
        return tiles[id] ?? fallback
    }
}

extension View {
    /// Report this view's frame in the Looks board's space to `report` (a picture a zoom can start from).
    func looksZoomSource(_ report: @escaping (CGRect) -> Void) -> some View {
        onGeometryChange(for: CGRect.self) { $0.frame(in: .named(LooksZoom.space)) } action: { report($0) }
    }
}

/// The overlay: a scrim, the picture at full resolution in its animated frame (scrolling when tall), and ×.
struct LooksZoomOverlay: View {
    let zoom: LooksZoom
    let summary: DesignRefSummary
    let onClose: (LooksZoom.Trigger) -> Void
    var onAppear: () -> Void = {}

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    private var bank: String { store?.bank ?? "" }

    var body: some View {
        GeometryReader { geo in
            let pixels = CGSize(width: summary.image?.width ?? 0, height: summary.image?.height ?? 0)
            let fit = LooksZoom.fitted(image: pixels, in: geo.size, margin: CicadaTheme.spacingXL * 2)
            let rect = zoom.frame(fitted: fit.frame)
            ZStack(alignment: .topLeading) {
                CicadaTheme.scrim
                    .opacity(zoom.expanded ? 1 : 0)
                    .contentShape(Rectangle())
                    .onTapGesture { onClose(.pointer) }
                    .accessibilityHidden(true)
                picture(scrolls: fit.scrolls && zoom.expanded)
                    .frame(width: rect.width, height: rect.height)
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .offset(x: rect.minX, y: rect.minY)
                IconButton(systemName: "xmark", help: Copy.Looks.closeEnlarged, accessibilityLabel: Copy.Looks.closeEnlarged,
                           shortcut: .cancelAction) { onClose(LooksZoom.currentTrigger()) }
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgPane))
                    .opacity(zoom.expanded ? 1 : 0)
                    .offset(x: geo.size.width - CicadaTheme.spacingXL - CicadaTheme.scaled(28), y: CicadaTheme.spacingMD)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Looks.enlarge)
        .onAppear(perform: onAppear)
        .task(id: "\(bank)|\(summary.image?.url ?? "-")") {
            guard let url = StoredPreviewPath.url(summary.image?.url) else { return }
            image = await PictureStore.shared.image(url, bank: bank)
        }
    }

    @ViewBuilder
    private func picture(scrolls: Bool) -> some View {
        GeometryReader { box in
            ScrollView(.vertical) {
                Group {
                    if let image {
                        Image(nsImage: image).resizable().interpolation(.high).aspectRatio(contentMode: .fit)
                    } else {
                        LooksPaletteField(colours: summary.palette)
                            .aspectRatio(summary.image?.aspect ?? 1.6, contentMode: .fit)
                    }
                }
                .frame(width: box.size.width)
            }
            .scrollDisabled(!scrolls)
            .scrollIndicators(scrolls ? .automatic : .hidden)
        }
        .background(CicadaTheme.bgPane)
    }
}
