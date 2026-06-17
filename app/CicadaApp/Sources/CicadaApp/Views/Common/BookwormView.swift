import SwiftUI

/// Reusable animated bookworm mascot for in-app surfaces (ingestion overlay,
/// empty states). Mirrors ``MenuBarManager``'s frame loop but as a pure SwiftUI
/// view decoupled from `NSStatusItem`, so any screen can show the same worm.
///
/// It cycles ``BookwormSprites.frames(for:)`` at the state's interval and
/// renders each frame through the proven ``BookwormRenderer.image(grid:…)``
/// template-image primitive (the same call ``InboxListView`` already uses for a
/// single static frame). The timer is torn down on `onDisappear` so the view
/// never leaks a running `Timer`.
struct BookwormView: View {
    let state: BookwormState
    var pointSize: CGFloat = 64
    var tint: Color = CicadaTheme.accent

    @State private var frameIndex = 0
    @State private var timer: Timer?

    private var frames: [[String]] {
        BookwormSprites.frames(for: state).frames
    }

    private var interval: TimeInterval {
        BookwormSprites.frames(for: state).interval
    }

    private var currentGrid: [String] {
        let f = frames
        guard !f.isEmpty else { return BookwormSprites.awakeOpen }
        return f[min(frameIndex, f.count - 1)]
    }

    var body: some View {
        Image(nsImage: BookwormRenderer.image(grid: currentGrid, pointSize: pointSize))
            .renderingMode(.template)
            .interpolation(.none)
            .foregroundStyle(tint)
            .onAppear { startTimer() }
            .onDisappear { stopTimer() }
            // Restart the loop when the state (and thus the frame set) changes.
            .onChange(of: state.caseName) { _, _ in
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
