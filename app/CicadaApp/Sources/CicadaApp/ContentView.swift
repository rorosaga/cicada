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
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 260)
        } detail: {
            detailContent
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(CicadaTheme.background)
        }
        .navigationSplitViewStyle(.prominentDetail)
        .onChange(of: graphVM.selectedEntity?.id) { _, newValue in
            withAnimation(.spring(duration: 0.3)) {
                columnVisibility = newValue != nil ? .detailOnly : .doubleColumn
            }
        }
        .task {
            await graphVM.loadGraph()
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        switch selectedTab {
        case .memory:
            GraphContainerView()
        case .topics:
            TopicsView()
        case .nudges:
            NudgeListView()
        case .clarifications:
            ClarificationListView()
        }
    }
}

// MARK: - Graph Container with Zoom Controls

struct GraphContainerView: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            // Entity detail card overlay (left)
            if let entity = graphVM.selectedEntity {
                HStack {
                    EntityDetailCard(entity: entity)
                        .frame(width: 380)
                        .padding(CicadaTheme.spacingLG)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                    Spacer()
                }
            }

            // Top-right: Sleep + Upload + Help buttons
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(showUploadOverlay: $showUploadOverlay)
                        .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            // Bottom-right: Filter + Zoom controls
            VStack {
                Spacer()
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        FilterButton()
                        ZoomControls()
                    }
                    .padding(CicadaTheme.spacingLG)
                }
            }

            // Upload overlay
            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
        .animation(.spring(duration: 0.3), value: showUploadOverlay)
    }
}

// MARK: - Filter Button

struct FilterButton: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var isHovered = false

    var body: some View {
        Button {
            graphVM.showFilterPopover.toggle()
        } label: {
            Image(systemName: "line.3.horizontal.decrease.circle")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(allEnabled ? (isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary) : CicadaTheme.accent)
                .frame(width: 36, height: 32)
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        .popover(isPresented: Binding(
            get: { graphVM.showFilterPopover },
            set: { graphVM.showFilterPopover = $0 }
        ), arrowEdge: .top) {
            FilterPopoverContent()
        }
    }

    private var allEnabled: Bool {
        graphVM.enabledTypes.count == EntityType.allCases.count
    }
}

struct FilterPopoverContent: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("FILTER CATEGORIES")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityType.allCases) { type in
                Button {
                    graphVM.toggleType(type)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.enabledTypes.contains(type) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 14))
                            .foregroundStyle(graphVM.enabledTypes.contains(type) ? CicadaTheme.entityColor(for: type) : CicadaTheme.textTertiary)

                        Text(type.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(graphVM.enabledTypes.contains(type) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 200)
        .background(CicadaTheme.surface)
    }
}

// MARK: - Zoom Controls

struct ZoomControls: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: 1) {
            ZoomButton(icon: "minus", action: { graphVM.zoomAction = .out })
            Divider().frame(height: 20).background(CicadaTheme.border)
            ZoomButton(icon: "plus", action: { graphVM.zoomAction = .zoomIn })
        }
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
    }
}

private struct ZoomButton: View {
    let icon: String
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .frame(width: 36, height: 32)
                .background(isHovered ? CicadaTheme.surfaceHover : .clear)
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}
