import SwiftUI

/// Onboarding v2, step 1 (G92, G217; 2026-10-22) — the card under the study room: the greeting (the saved name, else
/// the Mac account's — W7: one click corrects it), what Cicada is in one sentence, Continue (the one primary, ⏎; it
/// saves the name first, G117 R1) beside Set up later, and *Try the demo* as a quiet link (seam 2; hidden on a rerun,
/// R-OB19). Under 40 words. Every word sits on the card, none on art (DR-13). The card sits in the page, so it is ringed, never shadowed
/// (DR-9, DR-10; looks pass 2026-10-23). The card rises once (DR-65, DR-67);
/// Reduce Motion fades it in.
struct WelcomePage: View {
    let mode: OnboardingMode
    @Binding var name: String
    @Binding var editingName: Bool
    let busy: Bool
    let failure: String?
    /// Exports dropped on this page, held until Get started (R-OB2) — said, so a drop never vanishes silently.
    let waitingDrops: Int
    let onGetStarted: () -> Void
    let onSetUpLater: () -> Void
    let onTryDemo: () -> Void

    @FocusState private var nameFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = false

    var body: some View {
        let first = WelcomeName.firstWord(name)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if editingName {
                TextField(Copy.welcomeYourName, text: $name)
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.font(size: 22))
                    .focused($nameFocused)
                    .onSubmit { if OnboardingFlow.canStart(name: name) { editingName = false } }
                    .onAppear { nameFocused = true }
                    .accessibilityLabel(Copy.welcomeYourName)
            } else {
                Text(first.isEmpty ? Copy.welcomeHelloNoName : Copy.welcomeHello(first))
                    .font(CicadaTheme.displayFont(size: 40))
                    .tracking(CicadaTheme.displayTracking(size: 40))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
            }
            Text(Copy.welcomeLine)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if !first.isEmpty && !editingName {
                TextButton(title: Copy.welcomeNotYou(first), inline: true, flushLeading: true) { editingName = true }
            }
            if let failure {
                Text(failure).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if waitingDrops > 0 {
                Label(Copy.welcomeDropsWaiting(waitingDrops), systemImage: "tray.and.arrow.down")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                PrimaryActionButton(title: busy ? Copy.welcomeStarting : Copy.onboardingContinue, action: onGetStarted)
                    .disabled(busy || !OnboardingFlow.canStart(name: name))
                KeyHint("⏎")
                Spacer()
                if mode != .rerun {
                    TextButton(title: Copy.welcomeTryTheDemo, action: onTryDemo).disabled(busy)
                }
                TextButton(title: mode == .rerun ? Copy.welcomeClose : Copy.welcomeSetUpLater, action: onSetUpLater)
                    .disabled(busy)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .onboardingCard()
        .opacity(risen ? 1 : 0)
        .offset(y: risen || reduceMotion ? 0 : CicadaTheme.scaled(12))
        .onAppear {
            withAnimation(reduceMotion ? CicadaMotion.fade : CicadaMotion.panel(reduceMotion: false)) { risen = true }
        }
    }
}
