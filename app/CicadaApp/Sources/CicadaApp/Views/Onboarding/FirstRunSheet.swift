import SwiftUI

/// G117 — the four steps of the first-run sheet, in the order they present.
/// A pure, testable ordering (`next`) kept separate from `FirstRunSheet`
/// itself so the sequence is verifiable without standing up any SwiftUI.
enum OnboardingStep: Int, CaseIterable {
    case identity, engine, channel, sleep

    static func next(_ current: OnboardingStep) -> OnboardingStep? {
        OnboardingStep(rawValue: current.rawValue + 1)
    }

    static func previous(_ current: OnboardingStep) -> OnboardingStep? {
        OnboardingStep(rawValue: current.rawValue - 1)
    }
}

/// The four-step first-run wizard (G117): identity → engine → one capture
/// channel → first Sleep. Replaces `ContentView`'s old single-step
/// `ConnectView(isOnboarding:)` sheet — see `ContentView`'s own comment at
/// the call site for why that view is still reachable (Settings → Agents),
/// just no longer the first thing a new install shows.
///
/// Steps 1 and 2 (engine, channel) embed the ALREADY-SHIPPED
/// `EngineCard`/`IntegrationsView` wholesale rather than a hand-picked
/// subset (Ruling R4 — `IntegrationsView`'s three row types are `private`
/// to that file, so a "just these rows" component would mean either a
/// visibility change or a second, drifting row implementation; the whole
/// page, with one caption line above it, satisfies "one capture channel"
/// functionally since the person only needs to pick one row to connect).
/// Steps 0 and 3 (identity, sleep) drive their own advance because each
/// needs an async round trip before moving on — see their own doc comments.
struct FirstRunSheet: View {
    var bank: String
    var onFinished: () -> Void

    @State private var step: OnboardingStep = .identity

    var body: some View {
        VStack(spacing: 0) {
            stepHeader
            Divider()
            content
            Divider()
            footer
        }
        .frame(width: 780, height: 640)
    }

    @ViewBuilder private var content: some View {
        switch step {
        case .identity:
            OwnerIdentityStep(onContinue: { advance() })
        case .engine:
            ScrollView { EngineCard().padding(CicadaTheme.spacingXL) }
        case .channel:
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    Text(Copy.onboardingChannelCaption)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    IntegrationsView()
                }
                .padding(CicadaTheme.spacingXL)
            }
        case .sleep:
            OnboardingSleepStep(onFinished: finish)
        }
    }

    private var stepHeader: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(OnboardingStep.allCases, id: \.self) { s in
                    Capsule()
                        .fill(s.rawValue <= step.rawValue ? CicadaTheme.accent : CicadaTheme.border)
                        .frame(height: 4)
                }
            }
            Text(Copy.onboardingStepTitle(step))
                .font(CicadaTheme.titleFont)
                .foregroundStyle(CicadaTheme.textPrimary)
        }
        .padding(CicadaTheme.spacingXL)
    }

    /// Back/Next only ever govern the two PASSIVE steps (engine, channel) —
    /// identity and sleep drive their own advance (see `content` above), so
    /// this footer hides the buttons that would otherwise duplicate or race
    /// with a step's own action.
    private var footer: some View {
        HStack {
            if OnboardingStep.previous(step) != nil {
                Button("Back") { if let p = OnboardingStep.previous(step) { step = p } }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
            Button("Skip setup") { finish() }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textTertiary)
            if step == .engine || step == .channel {
                Button("Next") { advance() }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
            }
        }
        .padding(CicadaTheme.spacingXL)
    }

    private func advance() {
        if let next = OnboardingStep.next(step) {
            step = next
        } else {
            finish()
        }
    }

    /// Reached from the sleep step's own "Go to Graph" button, or from
    /// "Skip setup" at any point — either way the sheet is done with this
    /// bank and won't reopen on its own until Settings → General's "Run
    /// setup again" clears the flag (`OnboardingState.reset`).
    private func finish() {
        OnboardingState.markOnboarded(bank: bank)
        onFinished()
    }
}
