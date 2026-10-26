import AppKit
import SwiftUI

/// Report a problem… (tester readiness, 2026-10-26) — Help menu and Settings → General. The report is shown whole before
/// anything leaves the Mac: Copy, Save…, and one Send that copies it and opens `ProblemReport.destination` with a short
/// template (the person pastes; nothing is sent by itself). The sheet says whether that destination is public.
/// DR-5 (the accent only on Send, the sheet's one primary), DR-21 (monospaced report), DR-38 (each line said once),
/// DR-40 (neutral buttons for Copy and Save).
struct ReportProblemSheet: View {
    let onClose: () -> Void

    @State private var report: String?
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.ReportProblem.title)
                .font(CicadaTheme.font(size: 17, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(Copy.ReportProblem.lead)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ScrollView {
                Text(report ?? Copy.ReportProblem.loading)
                    .font(CicadaTheme.font(size: 11, design: .monospaced))
                    .foregroundStyle(report == nil ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
            }
            .background(CicadaTheme.bgPane)
            .clipShape(CicadaTheme.shape(6))
            Text(ProblemReport.destinationIsPublic ? Copy.ReportProblem.publicNote : Copy.ReportProblem.privateNote)
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: copied ? Copy.ReportProblem.copied : Copy.ReportProblem.copy, size: .compact,
                              isDisabled: report == nil) { copy() }
                NeutralButton(title: Copy.ReportProblem.save, size: .compact, isDisabled: report == nil) { save() }
                Spacer()
                NeutralButton(title: Copy.ReportProblem.close, size: .compact, shortcut: .cancelAction) { onClose() }
                PrimaryActionButton(title: Copy.ReportProblem.send) { send() }
                    .disabled(report == nil)
                    .help(Copy.ReportProblem.sendHelp)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(640), height: CicadaTheme.scaled(560))
        .background(CicadaTheme.bgBase)
        .task { await load() }
    }

    private func load() async {
        let header = ProblemReport.header(app: .current(), macOS: ProblemReport.macOSVersion)
        let backend = try? await APIClient.shared.fetchDiagnosticsReport()
        report = ProblemReport.compose(header: header, backend: backend)
    }

    private func copy() {
        guard let report else { return }
        AppPasteboard.copy(report)
        copied = true
    }

    private func save() {
        guard let report else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = ProblemReport.fileName()
        panel.allowedContentTypes = [.plainText]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        try? report.write(to: url, atomically: true, encoding: .utf8)
    }

    /// The person's own click: the report goes on the clipboard and the destination opens with its template.
    private func send() {
        guard let report else { return }
        AppPasteboard.copy(report)
        copied = true
        NSWorkspace.shared.open(ProblemReport.sendURL())
    }
}
