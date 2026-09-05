import SwiftUI

/// First-run sheet, step 3 (G117): the payoff step — trigger a real Sleep
/// cycle so the tour ends on "here's what the graph looks like after this
/// runs", not on a promise. Calls `SleepViewModel.triggerManually()`, the
/// SAME instance and method the Sleep page's own Consolidate button calls
/// (`CicadaApp`'s shared `.environment(sleepVM)`), rather than a second
/// sleep-trigger path — a cycle started here shows up identically on the
/// Sleep page if the person switches tabs mid-run.
///
/// "Go to Graph" finishes onboarding regardless of whether a cycle is still
/// running: a fresh bank's first cycle can take a while, and the person
/// should never be blocked in this sheet waiting for it — the Sleep page
/// and the menu-bar bookworm both keep tracking it after the sheet closes.
struct OnboardingSleepStep: View {
    var onFinished: () -> Void

    @Environment(SleepViewModel.self) private var sleepVM

    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            Spacer()
            BookwormView(state: bookwormState, pointSize: 120)
            Text(statusLine)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)

            if let errorMessage = sleepVM.errorMessage {
                Text(errorMessage)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(.red)
            }

            Button(sleepVM.isRunning ? "Sleeping…" : "Run Sleep now") {
                Task { await sleepVM.triggerManually() }
            }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.accent)
            .disabled(sleepVM.isRunning)

            Button("Go to Graph", action: onFinished)
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textTertiary)
            Spacer()
        }
        .padding(CicadaTheme.spacingXL)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Mirrors `deriveSleepPageMood`'s own precedence for the two facts this
    /// step actually needs (running, error) — the debt/hunger branches don't
    /// apply here, there's no "queue is overdue" story to tell on a bank
    /// that has never run Sleep once.
    private var bookwormState: BookwormState {
        if sleepVM.isRunning {
            return .sleeping(stage: max(1, min(5, sleepVM.status?.stage ?? 1)))
        }
        if let err = sleepVM.status?.error, !err.isEmpty {
            return .error
        }
        return .happy
    }

    private var statusLine: String {
        if sleepVM.isRunning {
            return "Consolidating what you've captured so far…"
        }
        return "Run a Sleep cycle now, or skip — it also runs on its own schedule."
    }
}
