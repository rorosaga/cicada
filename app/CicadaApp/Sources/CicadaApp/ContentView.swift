import SwiftUI

struct ContentView: View {
    @State private var selectedTab: AppTab = .memory
    @State private var columnVisibility: NavigationSplitViewVisibility = .doubleColumn

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(InboxViewModel.self) private var inboxVM

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(
                selectedTab: $selectedTab,
                inboxCount: inboxVM.pendingCount
            )
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 260)
        } detail: {
            detailContent
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(CicadaTheme.background)
        }
        .navigationSplitViewStyle(.prominentDetail)
        .task {
            await graphVM.loadGraph()
            await inboxVM.loadInbox()
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        switch selectedTab {
        case .memory:
            GraphContainerView(selectedTab: $selectedTab)
        case .topics:
            TopicsView(selectedTab: $selectedTab)
        case .sleep:
            SleepView(selectedTab: $selectedTab)
        case .inbox:
            InboxListView()
        }
    }
}

// MARK: - Graph Container with Zoom Controls

struct GraphContainerView: View {
    @Binding var selectedTab: AppTab
    @Environment(GraphViewModel.self) private var graphVM
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            // Top-right: Sleep + Upload + Help buttons
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(
                        selectedTab: $selectedTab,
                        showUploadOverlay: $showUploadOverlay
                    )
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

            // Node click → floating markdown-preview window over the graph.
            // Dimmed backdrop dismisses on tap; the card itself opens on the
            // raw Source view (what the user asked to see on click).
            if let entity = graphVM.selectedEntity {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { graphVM.clearSelection() }
                    .transition(.opacity)

                EntityDetailCard(entity: entity, defaultRaw: true)
                    .frame(maxWidth: 620, maxHeight: 680)
                    .padding(CicadaTheme.spacingXL)
                    .transition(.scale(scale: 0.97).combined(with: .opacity))
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
        graphVM.filter.allTypesSelected
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

            ForEach(EntityType.selectableCases) { type in
                Button {
                    graphVM.toggleType(type)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.types.contains(type) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 14))
                            .foregroundStyle(graphVM.filter.types.contains(type) ? CicadaTheme.entityColor(for: type) : CicadaTheme.textTertiary)

                        Text(type.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(graphVM.filter.types.contains(type) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.plain)
            }

            Divider()
                .background(CicadaTheme.border)
                .padding(.vertical, CicadaTheme.spacingXS)

            Text("STATUS")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
                .padding(.bottom, CicadaTheme.spacingXS)

            ForEach(EntityStatus.allCases, id: \.self) { status in
                Button {
                    graphVM.filter.toggleStatus(status)
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: graphVM.filter.statuses.contains(status) ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 14))
                            .foregroundStyle(graphVM.filter.statuses.contains(status) ? CicadaTheme.accent : CicadaTheme.textTertiary)

                        Text(status.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(graphVM.filter.statuses.contains(status) ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)

                        Spacer()
                    }
                    .padding(.vertical, 3)
                }
                .buttonStyle(.plain)
            }

            Divider()
                .background(CicadaTheme.border)
                .padding(.vertical, CicadaTheme.spacingXS)

            HStack {
                Text("MIN CONFIDENCE")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Text(String(format: "%.0f%%", graphVM.filter.minConfidence * 100))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }

            Slider(
                value: Binding(
                    get: { graphVM.filter.minConfidence },
                    set: { graphVM.filter.minConfidence = $0 }
                ),
                in: 0...1
            )
            .controlSize(.small)
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: 220)
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
            Divider().frame(height: 20).background(CicadaTheme.border)
            ZoomButton(icon: "arrow.down.left.and.arrow.up.right", action: { graphVM.zoomAction = .fit })
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
