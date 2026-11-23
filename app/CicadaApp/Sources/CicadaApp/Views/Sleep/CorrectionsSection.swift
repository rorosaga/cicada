import SwiftUI

/// G104 slice 3 (T4) — a run's "Corrections": what its edited conversations changed, in counts, and the pages they
/// archived, each one tap from its page and one tap from being put back. Hidden when the run revised nothing.
///
/// Applies DR-20/DR-47 (`SectionLabel`), DR-44 (a page is a `Tag`, opened by a click), DR-54 (a page by its name, its
/// id only when the graph does not hold it), DR-40 (Restore is a `TextButton`), DR-37/DR-38 (it lives in the run's own
/// details, says each thing once, and draws no card), DR-48 (rows, no hover lift). Counts and ids only.
struct CorrectionsSection: View {
    let runId: String
    let corrections: SleepRunDetail.Corrections?
    var onSelectEntity: ((String) -> Void)?
    @Environment(SleepViewModel.self) private var sleepVM: SleepViewModel?
    @Environment(Store.self) private var store: Store?

    var body: some View {
        if let c = corrections {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                SectionLabel(Copy.Corrections.title)
                ForEach(CorrectionsPresentation.lines(c), id: \.self) { line in
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let archived = CorrectionsPresentation.archivedLine(c) {
                    Text(archived)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(c.pagesArchived) { page in archivedRow(page) }
                }
                if let kept = CorrectionsPresentation.keptLine(c) {
                    Text(kept)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder
    private func archivedRow(_ page: SleepRunDetail.Corrections.ArchivedPage) -> some View {
        let names = store?.entityNames ?? .empty
        let label = RunDetailBlock.pageLabel(page.page, names: names)
        HStack(spacing: CicadaTheme.spacingSM) {
            Button { onSelectEntity?(page.page) } label: { Tag(text: label) }
                .buttonStyle(.cicadaPlain)
                .help(page.page)
                .accessibilityLabel(Copy.RunCard.openPage(label))
            if page.restorable {
                let busy = sleepVM?.restoringPages.contains(page.page) ?? false
                TextButton(title: busy ? Copy.Corrections.restoring : Copy.Corrections.restore,
                           help: Copy.Corrections.restoreHelp, inline: true) {
                    guard !busy, let sleepVM else { return }
                    Task { @MainActor in await sleepVM.restoreCorrectedPage(page.page, inRun: runId) }
                }
                .disabled(busy)
                if sleepVM?.restoreFailedPages.contains(page.page) == true {
                    Text(Copy.Corrections.restoreFailed)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else {
                Text(Copy.Corrections.restored)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }
}
