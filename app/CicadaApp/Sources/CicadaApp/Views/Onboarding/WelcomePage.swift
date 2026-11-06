import SwiftUI

/// Onboarding v2, step 1 (G92, G217; 2026-10-22) — the card under the study room: the greeting (the saved name, else
/// the Mac account's — W7: one click corrects it), what Cicada is in one sentence, Continue (the one primary, ⏎; it
/// saves the name first, G117 R1) and *Try the demo* and *Set up later* as the two quiet links beside it, one line (round 3) (seam 2; hidden on a rerun,
/// R-OB19). Under 40 words. Every word sits on the card, none on art (DR-13). The card sits in the page, so it is ringed, never shadowed
/// (DR-9, DR-10; looks pass 2026-10-23). The card rises once (DR-65, DR-67);
/// Reduce Motion fades it in.
struct WelcomePage: View {
    let mode: OnboardingMode
    @Binding var name: String
    @Binding var editingName: Bool
    /// The field holds the Mac account's name, not yet confirmed: say where it came from (tester readiness 2026-10-26).
    var fromMacAccount = false
    let busy: Bool
    let failure: String?
    /// Exports dropped on this page, held until Get started (R-OB2) — said, so a drop never vanishes silently.
    let waitingDrops: Int
    /// The leave action's words (Set up later, or Close on a rerun) and what it does: grouped with Continue, not in a corner.
    let leaveTitle: String
    let onGetStarted: () -> Void
    let onTryDemo: () -> Void
    let onLeave: () -> Void

    @FocusState private var nameFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = false

    var body: some View {
        let first = WelcomeName.firstWord(name)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if editingName && fromMacAccount {
                Text(Copy.welcomeHelloNoName)
                    .font(CicadaTheme.displayFont(size: 56))
                    .tracking(CicadaTheme.displayTracking(size: 56))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(Copy.welcomeNameFromMac)
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if editingName {
                TextField(Copy.welcomeYourName, text: $name)
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.font(size: 22))
                    .focused($nameFocused)
                    .onSubmit { if OnboardingFlow.canStart(name: name) { editingName = false } }
                    .onAppear { nameFocused = true }
                    .accessibilityLabel(Copy.welcomeYourName)
            } else {
                // ROR-118 round 3: the correction sits against the greeting it corrects, not at the far edge of the row.
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(first.isEmpty ? Copy.welcomeHelloNoName : Copy.welcomeHello(first))
                        .font(CicadaTheme.displayFont(size: 56))
                        .tracking(CicadaTheme.displayTracking(size: 56))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .accessibilityAddTraits(.isHeader)
                    if !first.isEmpty {
                        OnboardingLink(title: Copy.welcomeNotYou(first)) { editingName = true }
                    }
                    Spacer(minLength: 0)
                }
            }
            Text(Copy.welcomeLine)
                .font(CicadaTheme.displayFont(size: 24))
                .tracking(CicadaTheme.displayTracking(size: 24))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let failure {
                Text(failure).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if waitingDrops > 0 {
                Label(Copy.welcomeDropsWaiting(waitingDrops), systemImage: "tray.and.arrow.down")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            // One line for every choice (round 3): the filled Continue, then the two quiet ways out beside it.
            HStack(spacing: CicadaTheme.spacingXS) {
                PrimaryActionButton(title: busy ? Copy.welcomeStarting : Copy.onboardingContinue, large: true,
                                    action: onGetStarted)
                    .disabled(busy || !OnboardingFlow.canStart(name: name))
                    .padding(.trailing, CicadaTheme.spacingSM)
                if mode != .rerun {
                    OnboardingLink(title: Copy.welcomeTryTheDemo, action: onTryDemo).disabled(busy)
                }
                OnboardingLink(title: leaveTitle, action: onLeave).disabled(busy)
                Spacer(minLength: 0)
            }
            .padding(.top, CicadaTheme.spacingSM)
        }
        .padding(CicadaTheme.scaled(40))
        .onboardingCard()
        .opacity(risen ? 1 : 0)
        .offset(y: risen || reduceMotion ? 0 : CicadaTheme.scaled(12))
        .onAppear {
            withAnimation(reduceMotion ? CicadaMotion.fade : CicadaMotion.panel(reduceMotion: false)) { risen = true }
        }
    }
}
