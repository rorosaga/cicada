import SwiftUI

/// F-08 — while the demo bank is active, a persistent bar at the foot of the page area: what this is, *Restart tour*,
/// and the one big way back, *Finish setting up*. ContentView lays it out as a safe-area inset under the page and the
/// Reader, so it never covers a row, and the tour's scrim (an overlay on the page area above it) never covers it
/// (ruling R-DT8). A floating surface (DR-9/DR-10) whose one primary is *Finish setting up* (DR-40); nothing else on
/// the bar is tinted (DR-5). Outside the demo it draws nothing and takes no space.
struct DemoBanner: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(TourController.self) private var tour
    @Environment(GraphViewModel.self) private var graphVM
    @State private var leaving = false

    var body: some View {
        if DemoMode.isActive(store.banks.value) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Image(systemName: "sparkles")
                    .font(CicadaTheme.font(size: 14))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(32), height: CicadaTheme.scaled(32))
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgButton))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(Copy.Demo.bannerTitle)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .accessibilityAddTraits(.isHeader)
                    Text(Copy.Demo.bannerLine)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: CicadaTheme.spacingMD)
                TextButton(title: Copy.Demo.restartTour, help: Copy.Demo.restartTourHelp) { tour.requestStart() }
                PrimaryActionButton(title: Copy.Demo.finishSetup) { finish() }
                    .disabled(leaving)
                    .help(Copy.Demo.finishSetupHelp)
            }
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingMD)
            .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity)
            .background(CicadaTheme.bgBase)
            .accessibilityElement(children: .contain)
        }
    }

    /// The tour belongs to the demo it was showing, so it ends first (nothing remembered — the person decided nothing).
    private func finish() {
        guard !leaving else { return }
        leaving = true
        tour.interrupt()
        Task {
            let outcome = await DemoMode.leave(DemoMode.liveExit(store: store, router: router, graph: graphVM))
            leaving = false
            if case .failed = outcome { store.toast = Copy.Demo.leaveFailed }
        }
    }
}
