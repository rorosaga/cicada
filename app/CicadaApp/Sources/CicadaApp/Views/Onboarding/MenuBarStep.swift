import AppKit
import SwiftUI

/// Onboarding's *Meet your bookworm* step (owner 2026-10-23: "have a step where we show the guy in big with numbers going
/// up as animations and we explain what the numbers are, then when clicking next it appears in the taskbar").
///
/// The menu bar's own worm — its 18 × 18 sheet with the code-drawn badge (`BookwormView(artSet: .small)`), eight points
/// per art pixel, nearest-neighbour — over the card that says what its number means. The count rises as the badge
/// does when conversations arrive, holds, and an illustrated Sleep takes it away (`MenuBarStepModel`); the sprite's
/// own frames keep their sheet timings (ruling 18). It is the menu-bar item itself, shown big, not a second
/// illustration: no room on this step, no word on the art, every word on the card (DR-13). The card is ringed, never
/// shadowed (DR-9, DR-10). Under Reduce Motion the worm holds on its number (DR-66). Since onboarding v3 (2026-10-24)
/// the worm speaks for itself, and the flight is Done's closing beat: Continue, ⏎ and Skip all go on to Done, where the
/// same worm waits over the card. On a rerun the real menu-bar worm is already up there, so the step says "That's me"
/// and the real item says hello while the step talks about it (`MenuBarManager.greet`). DR-17 (the onboarding headline),
/// DR-21 (the count in words beside the badge), DR-40, DR-61's dated exception (`CicadaMotion.wormCount…`).
struct MenuBarStep: View {
    /// `StatusSnapshot.waitingForSleep` — the badge's own number — or nil before `/status` has answered.
    let waiting: Int?
    /// The real menu-bar worm is already showing (a rerun): the step points at it.
    var shownInMenuBar = false
    let busy: Bool
    let onBack: () -> Void
    let onSkip: () -> Void
    let onContinue: () -> Void

    /// Eight points per art pixel at 1×: 144 pt.
    static let wormPointSize: CGFloat = 144

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown: BookwormState = .happy

    private var target: Int { MenuBarStepModel.target(waiting: waiting) }

    var body: some View {
        VStack(spacing: CicadaTheme.scaled(OnboardingRoomLayout.cardGap)) {
            worm
            card
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            OnboardingHeadline(title: Copy.MeetWorm.title,
                               subline: shownInMenuBar ? Copy.MeetWorm.sublineShown : Copy.MeetWorm.subline)
            Text(Copy.MeetWorm.number)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Text(Copy.MeetWorm.goesDown)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingMD) {
                TextButton(title: Copy.onboardingBack, flushLeading: true, action: onBack)
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: Copy.onboardingSkip, action: onSkip).disabled(busy)
                PrimaryActionButton(title: Copy.onboardingContinue, action: onContinue)
                    .disabled(busy)
                KeyHint("⏎")
            }
        }
        .padding(CicadaTheme.spacingXL)
        .onboardingCard()
    }

    /// The worm and its caption, above the card, where the room sits over Welcome.
    private var worm: some View {
        MenuBarStepWorm(state: reduceMotion ? MenuBarStepModel.still(target: target) : shown,
                        caption: MenuBarStepModel.caption(waiting: waiting))
            // Restarts when the real count arrives or changes; ends with the step.
            .task(id: TaskKey(target: target, reduceMotion: reduceMotion)) { await play() }
    }

    private struct TaskKey: Equatable { let target: Int; let reduceMotion: Bool }

    /// The illustration's loop. Each beat holds for its own token's time; Reduce Motion plays nothing (the worm holds
    /// on its number above).
    private func play() async {
        guard !reduceMotion else { return }
        let beats = MenuBarStepModel.beats(target: target)
        while !Task.isCancelled {
            for beat in beats {
                shown = beat.state
                try? await Task.sleep(for: .seconds(beat.hold))
                if Task.isCancelled { return }
            }
        }
    }
}

/// The big menu-bar worm with its caption. Its number changes many times a second, so VoiceOver hears one fixed name
/// that says what the number means, not each value.
private struct MenuBarStepWorm: View {
    let state: BookwormState
    let caption: String

    var body: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            BookwormView(state: state, pointSize: MenuBarStep.wormPointSize, artSet: .small)
                .accessibilityElement(children: .ignore)
                .accessibilityAddTraits(.isImage)
                .accessibilityLabel(Copy.MeetWorm.imageLabel)
            Text(caption)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .monospacedDigit()
        }
    }
}

/// Reads where a SwiftUI view sits on screen, for the one AppKit animation that leaves the window (`MenuBarFlight`).
struct ScreenFrameAnchor: NSViewRepresentable {
    /// Holds the anchor's view weakly; asked once, at the click.
    final class Holder {
        weak var view: NSView?

        @MainActor
        func screenFrame() -> CGRect? {
            guard let view, let window = view.window else { return nil }
            let frame = window.convertToScreen(view.convert(view.bounds, to: nil))
            return frame.width > 0 && frame.height > 0 ? frame : nil
        }
    }

    let holder: Holder

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        holder.view = view
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) { holder.view = nsView }
}
