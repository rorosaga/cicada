import SwiftUI

/// Reusable animated bookworm mascot for in-app surfaces (ingestion overlay,
/// empty states, the Connect intro card). Mirrors ``MenuBarManager``'s frame
/// loop but as a pure SwiftUI view decoupled from `NSStatusItem`, so any
/// screen can show the same worm.
///
/// It cycles ``BookwormSprites.frames(for:)`` at the state's interval and
/// renders each frame through ``BookwormRenderer.image(grid:pointSize:)`` —
/// the COLOUR 24×24 palette sprites of G107, so there is no template mode and
/// no `tint:` (ruling R4: the palette is the mood; tinting would flatten it
/// to a silhouette). Sizes are multiples of 24 so cells are integer points
/// (R3). Task 4 of the G107 plan moves this loop onto a `TimelineView` with a
/// caption and Reduce Motion; until then the timer is torn down on
/// `onDisappear` so the view never leaks a running `Timer`.
struct BookwormView: View {
    let state: BookwormState
    var pointSize: CGFloat = 96

    @State private var frameIndex = 0
    @State private var timer: Timer?

    private var frames: [PixelGrid] {
        BookwormSprites.frames(for: state).frames
    }

    private var interval: TimeInterval {
        BookwormSprites.frames(for: state).interval
    }

    private var currentGrid: PixelGrid {
        let f = frames
        guard !f.isEmpty else { return BookwormSprites.awakeBase }
        return f[min(frameIndex, f.count - 1)]
    }

    var body: some View {
        // Colour art (G107): no template mode, no tint — the palette is the mood.
        Image(nsImage: BookwormRenderer.image(grid: currentGrid, pointSize: pointSize))
            .interpolation(.none)
            .frame(width: pointSize, height: pointSize)
            .onAppear { startTimer() }
            .onDisappear { stopTimer() }
            // Restart the loop when the FRAME SET changes — `spriteKey`, not
            // `caseName`, because the curious count and the sleep stage are
            // baked into the frames (R2).
            .onChange(of: state.spriteKey) { _, _ in
                frameIndex = 0
                startTimer()
            }
    }

    private func startTimer() {
        stopTimer()
        let count = frames.count
        guard count > 1 else { return }  // static state: no timer needed
        let t = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { _ in
            frameIndex = (frameIndex + 1) % count
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }
}
