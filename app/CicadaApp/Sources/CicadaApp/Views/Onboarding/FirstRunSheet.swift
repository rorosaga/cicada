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

    @Environment(Store.self) private var store
    @State private var step: OnboardingStep = .identity
    @State private var isCreatingDemoBank = false
    @State private var demoBankError: String?

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
        VStack(alignment: .trailing, spacing: CicadaTheme.spacingXS) {
            if let demoBankError {
                Text(demoBankError)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(.red)
            }
            HStack {
                if OnboardingStep.previous(step) != nil {
                    Button("Back") { if let p = OnboardingStep.previous(step) { step = p } }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                // G117 Task 5 — the demo-bank shortcut lives on every step
                // (not just step 0): whichever step a person stalls on, "just
                // let me look at it" is one click away rather than requiring
                // them to first back out to the start.
                Button(isCreatingDemoBank ? Copy.onboardingCreatingDemoBank : Copy.onboardingTryDemoBank) {
                    Task { await tryDemoBank() }
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textTertiary)
                .disabled(isCreatingDemoBank)
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
        }
        .padding(CicadaTheme.spacingXL)
    }

    /// `POST /banks/demo` already creates AND activates the bank server-side
    /// (`api/routers/banks.py::create_demo_bank`); the only client-side work
    /// left is telling `Store` the active bank moved. `refresh([.banks])`
    /// reuses the SAME bank-switch fan-out `ActivateBank` triggers
    /// (`Store.refresh`: sees `active != previous`, hydrates the new bank
    /// from its on-disk cache, then reconciles every domain) — there is no
    /// second, hand-rolled "switch banks" path to keep in sync with that one.
    private func tryDemoBank() async {
        demoBankError = nil
        isCreatingDemoBank = true
        defer { isCreatingDemoBank = false }
        do {
            _ = try await APIClient.shared.createDemoBank()
            await store.refresh([.banks])
            finish()
        } catch {
            demoBankError = "Couldn't create the demo bank — \(error.localizedDescription)"
        }
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
    ///
    /// Marks `store.bank` — the LIVE active bank — never the `bank` property
    /// captured when this struct was built. `tryDemoBank()` activates a new
    /// bank (`POST /banks/demo` + `store.refresh([.banks])`, which flips
    /// `store.bank` via `Store.hydrate(bank:)`) and then calls `finish()` on
    /// this SAME instance; `bank` still holds the pre-demo value from
    /// `ContentView`'s `FirstRunSheet(bank: store.bank)` call site, so
    /// marking it instead would permanently skip the tour for the person's
    /// real bank while leaving the demo bank unmarked.
    private func finish() {
        OnboardingState.markOnboarded(bank: store.bank)
        onFinished()
    }
}
