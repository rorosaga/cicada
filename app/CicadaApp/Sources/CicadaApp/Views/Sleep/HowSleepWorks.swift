import SwiftUI

/// The Sleep page's `?` popover (G125 Task 7) — replaces "About these
/// actions" there, since the Sleep/Upload buttons themselves leave this page
/// (R10: the one Consolidate control moved into the study list's footer, and
/// R-A7 later moved it again, into the hero).
/// Six short rows, one per Sleep stage plus Capture, mirroring the five-stage
/// batch `CLAUDE.md`'s "Core Architecture" section documents — this is the
/// same pipeline in plain language, not a second source of truth for it.
///
/// **The five stage rows are `SleepStages.all` (G125 v3 Task 5, P16).** They
/// used to be typed here; the strip on the page needed the same five, and two
/// hand-typed lists is how a pipeline acquires a second description. The copy
/// is unchanged — `SleepStageStripTests` pins all five titles, details and SF
/// Symbols as literals so this hoist cannot silently reword anything.
/// `capture` stays here, and only here: it is what happens BEFORE a cycle, not
/// a stage of one.
struct HowSleepWorksContent: View {

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text("HOW CICADA SLEEPS")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            row(icon: "tray.and.arrow.down",
                title: "Capture",
                detail: "Conversations, links and imports land as episodes — no model runs at capture time.")

            ForEach(SleepStages.all) { stage in
                row(icon: stage.symbol, title: stage.title, detail: stage.detail)
            }

            Divider().background(CicadaTheme.border)

            // Names the destination through `Copy.settingsSleep` rather
            // than retyping "Settings → Sleep" — `CopyConstantsTests`
            // greps the whole source tree for the literal.
            Text("Nightly runs never spend your plan's quota — only a cycle you start yourself does. Change when it runs in \(Copy.settingsSleep).")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360)
        .background(CicadaTheme.surface)
    }

    /// One popover row. Extracted so `capture` and the five hoisted stages are
    /// drawn by the same code — a second copy of this layout is how the
    /// leading row and the stage rows would drift apart visually.
    private func row(icon: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: icon)
                .font(CicadaTheme.font(size: 14))
                .foregroundStyle(CicadaTheme.accent)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(detail)
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
