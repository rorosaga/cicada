import SwiftUI

/// The text size's percentage, like Chrome's: a small pill at the top of the window that reads the new size on every
/// zoom (⌘+, ⌘−, ⌘0, the palette, the Settings slider) and leaves on its own (owner 2026-11-06). It is an overlay that
/// takes no click and no focus. It appears with the change it reports, never animated (a keyboard action never animates
/// its change); only its leaving fades, under `CicadaMotion` (DR-9: a floating surface, ringed; DR-23 sits it under
/// the titlebar band).
struct ZoomPill: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = false

    var body: some View {
        let pulse = ThemeStore.shared.zoomPulse
        let percent = Int((CicadaTheme.uiScale * 100).rounded())
        Group {
            if pulse > 0 {
                Text("\(percent)%")
                    .font(CicadaTheme.font(size: 15, weight: .medium).monospacedDigit())
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(.horizontal, CicadaTheme.scaled(16))
                    .padding(.vertical, CicadaTheme.scaled(8))
                    .floatingSurface(in: Capsule())
                    .opacity(shown ? 1 : 0)
                    .padding(.top, CicadaTheme.scaled(60))
                    .accessibilityLabel("\(Copy.textSize) \(percent)%")
            }
        }
        .allowsHitTesting(false)
        .task(id: pulse) {
            guard pulse > 0 else { return }
            var instant = Transaction(animation: nil)
            instant.disablesAnimations = true
            withTransaction(instant) { shown = true }
            AccessibilityNotification.Announcement("\(percent)%").post()
            try? await Task.sleep(for: .seconds(CicadaMotion.zoomPillHold))
            guard !Task.isCancelled else { return }
            withAnimation(CicadaMotion.zoomPillFade(reduceMotion: reduceMotion)) { shown = false }
        }
    }
}
