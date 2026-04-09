import SwiftUI

struct ClarificationListView: View {
    @Environment(ClarificationViewModel.self) private var viewModel

    var body: some View {
        ScrollView {
            if viewModel.clarifications.isEmpty {
                emptyState
            } else {
                LazyVStack(spacing: CicadaTheme.spacingSM) {
                    ForEach(viewModel.clarifications) { clarification in
                        ClarificationCardView(clarification: clarification) {
                            Task {
                                await viewModel.resolveClarification(id: clarification.id, action: "dismiss")
                            }
                        }
                    }
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.background)
        .task { await viewModel.loadClarifications() }
    }

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: "checkmark.circle")
                .font(.system(size: 40))
                .foregroundStyle(CicadaTheme.textTertiary)

            Text("No pending clarifications")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.top, 200)
    }
}
