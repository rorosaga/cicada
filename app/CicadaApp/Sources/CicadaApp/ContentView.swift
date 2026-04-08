import SwiftUI

struct ContentView: View {
    @State private var selectedTab: AppTab = .memory
    @State private var columnVisibility: NavigationSplitViewVisibility = .doubleColumn

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(NudgeViewModel.self) private var nudgeVM
    @Environment(ClarificationViewModel.self) private var clarificationVM

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(
                selectedTab: $selectedTab,
                nudgeCount: nudgeVM.pendingCount,
                clarificationCount: clarificationVM.pendingCount
            )
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 240)
        } detail: {
            ZStack {
                switch selectedTab {
                case .memory:
                    GraphContainerView()
                case .nudges:
                    NudgeListView()
                case .clarifications:
                    ClarificationListView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(CicadaTheme.background)
        }
        .navigationSplitViewStyle(.prominentDetail)
        .onChange(of: graphVM.selectedEntity?.id) { _, newValue in
            withAnimation(.spring(duration: 0.3)) {
                columnVisibility = newValue != nil ? .detailOnly : .doubleColumn
            }
        }
    }
}

struct GraphContainerView: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        ZStack(alignment: .leading) {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            if let entity = graphVM.selectedEntity {
                EntityDetailCard(entity: entity)
                    .frame(width: 380)
                    .padding(CicadaTheme.spacingLG)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
    }
}
