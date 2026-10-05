import AppKit
import SwiftUI

/// Plays sprite frames by swapping one layer's `contents` at each frame boundary, so SwiftUI never re-renders for a
/// frame. Measured 2026-10-05 (macOS 26): a `TimelineView` whose entries fall under ~0.3 s apart makes SwiftUI lay
/// the whole window out at the display rate — 240 host layouts a second for 4 ticks a second — and the room's sheets
/// run at 80–150 ms, so the Sleep page spent 12% of a core redrawing nothing. Callers still choose the frame
/// (`frame`, evaluated once per boundary); `tracks` only say when to ask (`SpriteFrameSchedule`'s rule).
///
/// Mount it only while the art may move: the caller shows a still SwiftUI frame for Reduce Motion, a paused host, an
/// unseen window and `ImageRenderer` snapshots (which cannot draw a platform view), and that teardown stops the timer.
struct SpriteLayerPlayer: NSViewRepresentable {
    let tracks: [SpriteFrameSchedule.Track]
    let frame: (Date) -> CGImage?

    func makeNSView(context: Context) -> SpriteLayerPlayerView { SpriteLayerPlayerView() }

    func updateNSView(_ view: SpriteLayerPlayerView, context: Context) { view.play(tracks: tracks, frame: frame) }

    static func dismantleNSView(_ view: SpriteLayerPlayerView, coordinator: ()) { view.stop() }
}

final class SpriteLayerPlayerView: NSView {
    private var tracks: [SpriteFrameSchedule.Track] = []
    private var frameAt: ((Date) -> CGImage?)?
    private var timer: Timer?
    /// The boundary the armed timer waits for; `nil` while stopped or out of a window.
    private(set) var nextBoundary: Date?
    /// Frames drawn since creation — one per boundary or caller update, never one per display frame.
    private(set) var drawCount = 0
    var now: () -> Date = Date.init

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layerContentsRedrawPolicy = .never
        // Whole pixels, as the SwiftUI path's `.interpolation(.none)`; a swap is instant, never a crossfade.
        layer?.magnificationFilter = .nearest
        layer?.minificationFilter = .nearest
        layer?.contentsGravity = .resize
        layer?.actions = ["contents": NSNull()]
    }

    required init?(coder: NSCoder) { nil }

    // Inert art: the room's hotspots take every click.
    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    func play(tracks: [SpriteFrameSchedule.Track], frame: @escaping (Date) -> CGImage?) {
        self.tracks = tracks
        frameAt = frame
        tick()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        nextBoundary = nil
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window == nil { stop() } else { tick() }
    }

    /// Draws the frame for now, then arms one timer for the next boundary — only while in a window.
    func tick() {
        stop()
        let date = now()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        layer?.contents = frameAt?(date)
        CATransaction.commit()
        drawCount += 1
        guard window != nil, let next = Self.nextBoundary(after: date, tracks: tracks) else { return }
        nextBoundary = next
        let timer = Timer(fire: next, interval: 0, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        timer.tolerance = CicadaMotion.spriteBoundaryTolerance
        // `.common`, so the art keeps its timing while a scroll or a menu tracks the pointer.
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    /// The union of the tracks' boundaries — the same dates the old `TimelineView(SpriteFrameSchedule)` woke at.
    static func nextBoundary(after date: Date, tracks: [SpriteFrameSchedule.Track]) -> Date? {
        tracks.compactMap { SpriteFrameSchedule.nextBoundary(after: date, track: $0) }.min()
    }
}
