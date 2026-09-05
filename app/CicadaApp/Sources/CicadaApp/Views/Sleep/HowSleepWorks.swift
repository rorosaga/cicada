import SwiftUI

/// The Sleep page's `?` popover (G125 Task 7) — replaces "About these
/// actions" there, since the Sleep/Upload buttons themselves leave this page
/// (R10: the one Consolidate control moved into the study list's footer).
/// Six short rows, one per Sleep stage plus Capture, mirroring the five-stage
/// batch `CLAUDE.md`'s "Core Architecture" section documents — this is the
/// same pipeline in plain language, not a second source of truth for it.
struct HowSleepWorksContent: View {
    private struct Row: Identifiable {
        let id: String
        let icon: String
        let title: String
        let detail: String
    }

    private static let rows: [Row] = [
        Row(id: "capture", icon: "tray.and.arrow.down",
            title: "Capture",
            detail: "Conversations, links and imports land as episodes — no model runs at capture time."),
        Row(id: "stage1", icon: "book",
            title: "Stage 1 · Read",
            detail: "Each episode is read once for people, projects, tools and ideas."),
        Row(id: "stage2", icon: "arrow.triangle.merge",
            title: "Stage 2 · Sort",
            detail: "New mentions are matched against what you already have."),
        Row(id: "stage3", icon: "questionmark.circle",
            title: "Stage 3 · Decide",
            detail: "Contradictions become questions in your Inbox; old beliefs fade."),
        Row(id: "stage4", icon: "sparkles",
            title: "Stage 4 · Notice",
            detail: "Habits that recur become skills."),
        Row(id: "stage5", icon: "checkmark.seal",
            title: "Stage 5 · File",
            detail: "Everything is written to the graph and committed with its provenance."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text("HOW CICADA SLEEPS")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            ForEach(Self.rows) { row in
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    Image(systemName: row.icon)
                        .font(CicadaTheme.font(size: 14))
                        .foregroundStyle(CicadaTheme.accent)
                        .frame(width: 20)

                    VStack(alignment: .leading, spacing: 4) {
                        Text(row.title)
                            .font(CicadaTheme.font(size: 13, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(row.detail)
                            .font(CicadaTheme.font(size: 11))
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider().background(CicadaTheme.border)

            // Names the destination through `Copy.settingsSchedule` rather
            // than retyping "Settings → Schedule" — `CopyConstantsTests`
            // greps the whole source tree for the literal.
            Text("Nightly runs never spend your plan's quota — only a cycle you start yourself does. Change when it runs in \(Copy.settingsSchedule).")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360)
        .background(CicadaTheme.surface)
    }
}
