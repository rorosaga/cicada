import SwiftUI

/// G245 (owner 2026-11-24, answer 6) — "Read your lists every day": the one shell line for the person's own cron or launchd,
/// a Copy control, the exposure said plainly and a short launchd example. Cicada starts nothing here and schedules nothing;
/// the line is fetched from the backend, which is the one place that words it (`reading_prompt.daily_command`). DR-40
/// (one quiet button), DR-39 (the example folds, the person's own open or closed, never synced).
struct DailyCommandRow: View {
    let model: ReadingAgentModel
    @Environment(Store.self) private var store
    @AppStorage("cicada.reading.dailyExampleOpen") private var exampleOpen = false

    var body: some View {
        SettingsRow(.readingDaily, title: Copy.ListRun.title, detail: Copy.ListRun.sentence) {
            NeutralButton(title: Copy.ListRun.copyCommand, size: .compact, help: Copy.ListRun.copyCommandHelp) {
                Task {
                    if let line = await model.dailyCommand() {
                        AppPasteboard.copy(line)
                        store.toast = Copy.ListRun.copied
                    } else {
                        store.toast = Copy.ListRun.unavailable
                    }
                }
            }
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(Copy.ListRun.exposure)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                DisclosureHeader(title: Copy.ListRun.exampleFold, isOpen: exampleOpen) { exampleOpen.toggle() }
                if exampleOpen {
                    Text(Copy.ListRun.launchdIntro)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(Copy.ListRun.launchdExample)
                        .font(CicadaTheme.monoFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(CicadaTheme.spacingMD)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.codeBackground))
                        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).stroke(CicadaTheme.border, lineWidth: 1))
                }
            }
        }
    }
}
