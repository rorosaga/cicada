import SwiftUI

/// ROR-126 — an export staged on the Welcome is committed only when the person begins, so this is where they choose
/// what it brings in first: the same start date and ticks as the intake preview (`ExportChoiceView`), one section per
/// staged export that has a list to choose from. Done keeps the choice; nothing becomes an episode here.
struct WelcomeExportChoiceSheet: View {
    @Environment(IntakeRouter.self) private var intake
    let onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(intake.welcomeDrops.filter { $0.preview.offersChoice }) { drop in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        VendorMark(origin: drop.preview.origin, size: CicadaTheme.scaled(20))
                        Text(IntakeSummary.previewTitle(drop.preview)).font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                    }
                    ExportChoiceView(preview: drop.preview) { intake.updateWelcomeDrop(drop.id, $0) }
                }
            }
            HStack {
                Spacer()
                PrimaryActionButton(title: Copy.seeHowDone, action: onDone)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(560))
    }
}
