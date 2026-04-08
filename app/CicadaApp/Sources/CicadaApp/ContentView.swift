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
    }

    @ViewBuilder
    private var detailContent: some View {
        switch selectedTab {
        case .memory:
            GraphContainerView()
        case .nudges:
            NudgeListView()
        case .clarifications:
            ClarificationListView()
        case .upload:
            ConversationUploadView()
        }
    }
}

// MARK: - Graph Container with Zoom Controls

struct GraphContainerView: View {
    @Environment(GraphViewModel.self) private var graphVM

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

            // Topics list (right side)
            HStack {
                Spacer()
                if graphVM.showTopicsList {
                    TopicsListPanel()
                        .frame(width: 260)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }

            // Zoom controls + filter + topics toggle (bottom-right)
            VStack {
                Spacer()
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        FilterButton()
                        TopicsListToggle()
                        ZoomControls()
                    }
                    .padding(CicadaTheme.spacingLG)
                }
            }
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
        .animation(.spring(duration: 0.3), value: graphVM.showTopicsList)
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

// MARK: - Topics List Toggle

struct TopicsListToggle: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var isHovered = false

    var body: some View {
        Button {
            graphVM.showTopicsList.toggle()
        } label: {
            Image(systemName: "list.bullet")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(graphVM.showTopicsList ? CicadaTheme.accent : (isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary))
                .frame(width: 36, height: 32)
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
    }
}

// MARK: - Topics List Panel

struct TopicsListPanel: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Image(systemName: "circle.grid.2x2.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text("TOPICS")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Button {
                    graphVM.showTopicsList = false
                } label: {
                    Image(systemName: "sidebar.right")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)

            Divider().background(CicadaTheme.border)

            // Nodes list
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(graphVM.filteredEntities.sorted(by: { $0.name < $1.name })) { entity in
                        TopicRow(entity: entity)
                    }
                }
                .padding(.vertical, CicadaTheme.spacingXS)
            }
        }
        .frame(maxHeight: .infinity)
        .padding(.top, CicadaTheme.spacingLG)
        .padding(.bottom, 60) // leave room for bottom controls
        .glassCard()
    }
}

private struct TopicRow: View {
    let entity: Entity
    @Environment(GraphViewModel.self) private var graphVM
    @State private var isHovered = false

    var body: some View {
        Button {
            graphVM.selectEntity(id: entity.id)
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: entity.type.icon)
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.entityColor(for: entity.type))
                    .frame(width: 16)

                Text(entity.name)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)

                Spacer()
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingXS + 2)
            .background(isHovered || graphVM.selectedEntity?.id == entity.id ? CicadaTheme.surfaceHover : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 4))
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .padding(.horizontal, CicadaTheme.spacingXS)
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

// MARK: - Conversation Upload View

struct ConversationUploadView: View {
    @State private var isDragOver = false
    @State private var uploadedFiles: [String] = []

    var body: some View {
        VStack(spacing: CicadaTheme.spacingXL) {
            Spacer()

            // Drop zone
            VStack(spacing: CicadaTheme.spacingLG) {
                Image(systemName: "arrow.up.doc")
                    .font(.system(size: 40))
                    .foregroundStyle(isDragOver ? CicadaTheme.accent : CicadaTheme.textTertiary)

                Text("Upload Conversation Export")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)

                Text("Drop a ChatGPT or Claude export file here\n(JSON or HTML)")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .multilineTextAlignment(.center)

                Button {
                    pickFile()
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "folder")
                        Text("Choose File")
                    }
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.vertical, CicadaTheme.spacingMD)
                    .background(CicadaTheme.accent.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: 400)
            .padding(CicadaTheme.spacingXXL)
            .glassCard()
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(isDragOver ? CicadaTheme.accent : .clear, lineWidth: 2)
                    .animation(.easeInOut(duration: 0.2), value: isDragOver)
            )

            // Uploaded files list
            if !uploadedFiles.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text("Queued for next Sleep cycle")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)

                    ForEach(uploadedFiles, id: \.self) { file in
                        HStack {
                            Image(systemName: "doc.text")
                                .foregroundStyle(CicadaTheme.accent)
                            Text(file)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                            Spacer()
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(Color(hex: 0x22C55E))
                        }
                        .padding(CicadaTheme.spacingMD)
                        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    }
                }
                .frame(maxWidth: 400)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.background)
    }

    private func pickFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select a ChatGPT or Claude conversation export"

        if panel.runModal() == .OK, let url = panel.url {
            withAnimation(.spring(duration: 0.3)) {
                uploadedFiles.append(url.lastPathComponent)
            }
        }
    }
}
