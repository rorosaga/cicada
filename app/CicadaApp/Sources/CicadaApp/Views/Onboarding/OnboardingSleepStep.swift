import SwiftUI

/// Track P R3/R4 — the pure half of "does this install actually consolidate
/// on its own?", so the sentence the first-run sheet shows is a function of
/// the schedule the backend reports rather than a hand-written promise. The
/// shipped default is `manual` (`api/services/sleep_scheduler.py::_DEFAULT`,
/// whose `register_job` registers no job at all), which is why the old copy
/// — "it also runs on its own schedule" — was false on every new install.
///
/// Only the sentence lives here: the toggle's rule moved to `ScheduleToggle`
/// (Track Z Z0, Z-P27), so the Sleep page's lamp and this step share one
/// definition and a later redesign can delete this step without the rule.
enum OnboardingSchedule {
    static func line(_ cfg: ScheduleConfig) -> String {
        switch cfg.mode {
        case "daily":
            return "Cicada will consolidate nightly at \(cfg.hour):\(String(format: "%02d", cfg.minute))."
        case "interval":
            return "Cicada will consolidate every \(cfg.intervalHours) hours."
        case "after_import":
            return "Cicada will consolidate a few minutes after new material arrives."
        default:
            return "Sleep runs only when you ask. Turn this on and Cicada consolidates while you sleep."
        }
    }
}

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
///
/// Track P R3 — the step also carries the nightly-schedule toggle. The old
/// status line ended "…or skip — it also runs on its own schedule", which a
/// fresh install never did (`sleep_scheduler._DEFAULT` is `manual`, and
/// `register_job` registers nothing for it): the tour's last sentence about
/// automation was the one thing it got wrong. The honest fix is to *offer*
/// the schedule rather than soften the claim, so the toggle writes the same
/// `PUT /sleep/schedule` `Settings → Sleep` drives — one writer, one
/// endpoint, never a second scheduling path — and the sentence under it is
/// derived from the `ScheduleConfig` that write returns.
struct OnboardingSleepStep: View {
    var onFinished: () -> Void

    @Environment(SleepViewModel.self) private var sleepVM

    /// Mirrors `SettingsSleepView`'s one-shot load guard: `.task` re-runs
    /// whenever the view's identity changes (a step re-entered by going
    /// back), and a second `load()` would clobber a schedule write still in
    /// flight with the pre-write value.
    @State private var loadedOnce = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            Spacer()
            BookwormView(state: bookwormState, pointSize: 120)
            Text(statusLine)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)

            Toggle(Copy.onboardingRunNightly, isOn: Binding(
                get: { ScheduleToggle.isOn(sleepVM.schedule) },
                set: { on in
                    Task { await sleepVM.updateSchedule(ScheduleToggle.toggled(on: on, current: sleepVM.schedule)) }
                }
            ))
            .toggleStyle(.switch)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .frame(maxWidth: 420, alignment: .leading)

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
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
            }
        }
    }

    /// Mirrors `deriveSleepPageMood`'s own precedence for the two facts this
    /// step actually needs (running, error) — the debt/hunger branches don't
    /// apply here, there's no "queue is overdue" story to tell on a bank
    /// that has never run Sleep once.
    private var bookwormState: BookwormState {
        if sleepVM.isRunning {
            // R-Z14: the wire counts COMPLETED stages; this site was the
            // third clamp that said "stage 1" while Sort ran.
            return .sleeping(stage: activeStage(completed: sleepVM.status?.stage ?? 0))
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
        return OnboardingSchedule.line(sleepVM.schedule)
    }
}
