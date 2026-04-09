import SwiftUI

struct NudgeListView: View {
    @Environment(NudgeViewModel.self) private var viewModel

    var body: some View {
        ScrollView {
            if viewModel.nudges.isEmpty {
                emptyState
            } else {
                LazyVStack(spacing: CicadaTheme.spacingSM) {
                    ForEach(viewModel.nudges) { nudge in
                        NudgeCardView(nudge: nudge) {
                            Task {
                                await viewModel.resolveNudge(id: nudge.id, action: "archive")
                            }
                        }
                    }
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.background)
        .task { await viewModel.loadNudges() }
    }

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: "checkmark.circle")
                .font(.system(size: 40))
                .foregroundStyle(CicadaTheme.textTertiary)

            Text("No pending nudges")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.top, 200)
    }
}
