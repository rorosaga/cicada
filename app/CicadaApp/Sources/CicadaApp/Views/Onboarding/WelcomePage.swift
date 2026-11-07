import SwiftUI

/// Onboarding v2, step 1 (G92, G217; 2026-10-22) — the card under the study room: the greeting (the saved name, else
/// the Mac account's — W7: one click corrects it), what Cicada is in one sentence, Continue (the one primary, ⏎; it
/// saves the name first, G117 R1) and *Try the demo* beside it as an outlined button (round 4; seam 2, hidden on a rerun,
/// R-OB19); *Set up later* is the window's top-corner exit. Under 40 words. Every word sits on the card, none on art (DR-13). The card sits in the page, so it is ringed, never shadowed
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
    /// ROR-126 — opens the chooser for a staged export that has chats to choose from.
    var onChooseDrops: (() -> Void)? = nil
    let onGetStarted: () -> Void
    let onTryDemo: () -> Void

    @FocusState private var nameFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = false
    /// What the name was when its line opened — Esc puts it back.
    @State private var nameBeforeEdit = ""

    var body: some View {
        let first = WelcomeName.firstWord(name)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            greeting(first: first)
            if editingName && fromMacAccount {
                Text(Copy.welcomeNameFromMac)
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
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
                HStack(spacing: CicadaTheme.spacingSM) {
                    Label(Copy.welcomeDropsWaiting(waitingDrops), systemImage: "tray.and.arrow.down")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    // ROR-126: the choice comes before Begin, because Begin is when a staged export is read in.
                    if let onChooseDrops { TextButton(title: Copy.exportChoiceWelcomeButton, action: onChooseDrops) }
                }
            }
            // Round 4: the filled Continue and, beside it, the demo as an outlined button. The way out of the flow
            // (Set up later) is the window's top-corner exit (`OnboardingLeaveLink`), the same on every step.
            HStack(spacing: CicadaTheme.spacingMD) {
                PrimaryActionButton(title: busy ? Copy.welcomeStarting : Copy.onboardingContinue, large: true,
                                    action: onGetStarted)
                    .disabled(busy || !OnboardingFlow.canStart(name: name))
                if mode != .rerun {
                    OnboardingOutlinedButton(title: Copy.welcomeTryTheDemo, action: onTryDemo).disabled(busy)
                }
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

    /// Owner 2026-11-06: the greeting is one line that keeps its place as the page's lead, a notch smaller than before.
    private static let greetingSize: CGFloat = 44

    /// "Hello, Maya." — the name is a small pencil's to change. The pencil turns the name into a line to fill in place
    /// (no box, the same type); ⏎ keeps it, Esc puts back what it was (DR-9: a hairline, no shadow).
    @ViewBuilder
    private func greeting(first: String) -> some View {
        let size = Self.greetingSize
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            if editingName {
                Text(Copy.welcomeGreetingLead + " ").greetingType(size)
                nameLine(size: size)
                Text(".").greetingType(size)
            } else if first.isEmpty {
                Text(Copy.welcomeHelloNoName).greetingType(size)
            } else {
                Text(Copy.welcomeHello(first)).greetingType(size)
                Button {
                    editingName = true
                } label: {
                    Image(systemName: "pencil")
                        .font(CicadaTheme.font(size: 16, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .padding(.leading, CicadaTheme.spacingSM)
                .help(Copy.welcomeEditName)
                .accessibilityLabel(Copy.welcomeEditName)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isHeader)
    }

    /// The name as a line to fill: a plain field over a hidden copy of its text, so the line is as wide as the words
    /// (and never narrower than a name's worth), with a hairline under it.
    private func nameLine(size: CGFloat) -> some View {
        ZStack(alignment: .leading) {
            Text(name.isEmpty ? Copy.welcomeYourName : name).greetingType(size).opacity(0).lineLimit(1)
            TextField(Copy.welcomeYourName, text: $name)
                .textFieldStyle(.plain)
                .font(CicadaTheme.displayFont(size: size))
                .tracking(CicadaTheme.displayTracking(size: size))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($nameFocused)
                .onSubmit { if OnboardingFlow.canStart(name: name) { editingName = false } }
                .onExitCommand {
                    name = nameBeforeEdit
                    if OnboardingFlow.canStart(name: name) { editingName = false }
                }
                .onAppear { nameBeforeEdit = name; nameFocused = true }
                .accessibilityLabel(Copy.welcomeYourName)
        }
        .padding(.bottom, CicadaTheme.scaled(2))
        .overlay(alignment: .bottom) {
            Rectangle().fill(CicadaTheme.textSecondary).frame(height: 1)
        }
    }
}

private extension View {
    func greetingType(_ size: CGFloat) -> some View {
        font(CicadaTheme.displayFont(size: size))
            .tracking(CicadaTheme.displayTracking(size: size))
            .foregroundStyle(CicadaTheme.textPrimary)
    }
}
