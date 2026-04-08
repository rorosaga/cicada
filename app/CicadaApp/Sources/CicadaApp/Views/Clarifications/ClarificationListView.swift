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
                            withAnimation(.spring(duration: 0.3)) {
                                viewModel.resolveClarification(id: clarification.id)
                            }
                        }
                    }
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.background)
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
