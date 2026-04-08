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

            // Zoom controls (bottom-right)
            VStack {
                Spacer()
                HStack {
                    Spacer()
                    ZoomControls()
                        .padding(CicadaTheme.spacingLG)
                }
            }
        }
        .animation(.spring(duration: 0.3), value: graphVM.selectedEntity?.id)
    }
}

// MARK: - Zoom Controls

struct ZoomControls: View {
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: 1) {
            ZoomButton(icon: "minus", action: { graphVM.zoomAction = .out })
            Divider().frame(height: 20).background(CicadaTheme.border)
            ZoomButton(icon: "arrow.counterclockwise", action: { graphVM.zoomAction = .reset })
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
