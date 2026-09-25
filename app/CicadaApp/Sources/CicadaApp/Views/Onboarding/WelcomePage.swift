import SwiftUI

/// F-01 (G145; owner: "I definitely like A's welcome page") — A-01's small card on the full-bleed meadow: the greeting
/// (the saved name, else the Mac account's — W7: one click corrects it), the promise (R-OB17), the marks of the agents
/// Cicada works with, Get started (the one primary, ⏎) beside Set up later, and *Try the demo* with real presence
/// (seam 2; hidden on a rerun, R-OB19). Every word sits on the card, none on paint (DR-13). The card rises once
/// (DR-65, DR-67); Reduce Motion fades it in.
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
            Text(Copy.welcomeEyebrow).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
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
            Text(Copy.welcomeTagline)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textSecondary)
            Text(Copy.welcomePromise).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if !first.isEmpty && !editingName {
                TextButton(title: Copy.welcomeNotYou(first), inline: true) { editingName = true }
            }
            if let failure {
                Text(failure).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if waitingDrops > 0 {
                Label(Copy.welcomeDropsWaiting(waitingDrops), systemImage: "tray.and.arrow.down")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            marks
            HStack(spacing: CicadaTheme.spacingSM) {
                PrimaryActionButton(title: busy ? Copy.welcomeStarting : Copy.onboardingGetStarted, action: onGetStarted)
                    .disabled(busy || !OnboardingFlow.canStart(name: name))
                KeyHint("⏎")
                Spacer()
                TextButton(title: mode == .rerun ? Copy.welcomeClose : Copy.welcomeSetUpLater, action: onSetUpLater)
                    .disabled(busy)
            }
            if mode != .rerun { demoRow }
        }
        .padding(CicadaTheme.spacingXL)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .opacity(risen ? 1 : 0)
        .offset(y: risen || reduceMotion ? 0 : CicadaTheme.scaled(12))
        .onAppear {
            withAnimation(reduceMotion ? CicadaMotion.fade : CicadaMotion.panel(reduceMotion: false)) { risen = true }
        }
    }

    private var marks: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.welcomeWorksWith).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Spacer(minLength: CicadaTheme.spacingSM)
            ForEach(WelcomeMarks.entries) { entry in
                AgentMark(entry: entry, size: 18).help(entry.name).accessibilityLabel(entry.name)
            }
        }
        .padding(CicadaTheme.spacingSM)
        .background(CicadaTheme.bgPane, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }

    /// The demo's real presence (owner decision 1): its own inset, no rule above it (DR-11).
    private var demoRow: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "sparkles").foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.welcomeJustLooking).font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.welcomeDemoBlurb).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.welcomeTryTheDemo, isDisabled: busy, action: onTryDemo)
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.bgPane, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }
}
