import SwiftUI

// MARK: - Top Bar Controls (Sleep + Upload + Help)

struct TopBarControls: View {
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(NudgeViewModel.self) private var nudgeVM
    @Environment(ClarificationViewModel.self) private var clarificationVM

    @Binding var showUploadOverlay: Bool
    @State private var showHelpOverlay = false
    @State private var isSleepRunning = false
    @State private var sleepProgress: String = ""

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // Sleep button
            Button {
                triggerSleep()
            } label: {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if isSleepRunning {
                        ProgressView()
                            .controlSize(.small)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: "moon.fill")
                            .font(.system(size: 12))
                    }
                    Text(isSleepRunning ? "Sleeping..." : "Sleep")
                        .font(.system(size: 12, weight: .medium))
                }
                .foregroundStyle(isSleepRunning ? CicadaTheme.textTertiary : CicadaTheme.accent)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.spacingSM)
            }
            .buttonStyle(.plain)
            .disabled(isSleepRunning)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
            .help(sleepProgress.isEmpty ? "Run memory consolidation" : sleepProgress)

            // Upload button
            Button {
                withAnimation(.spring(duration: 0.3)) {
                    showUploadOverlay = true
                }
            } label: {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "arrow.up.doc")
                        .font(.system(size: 12))
                    Text("Upload")
                        .font(.system(size: 12, weight: .medium))
                }
                .foregroundStyle(CicadaTheme.textSecondary)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.spacingSM)
            }
            .buttonStyle(.plain)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)

            // Help button
            Button {
                withAnimation(.spring(duration: 0.25)) {
                    showHelpOverlay.toggle()
                }
            } label: {
                Image(systemName: "questionmark.circle")
                    .font(.system(size: 13))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 32, height: 28)
            }
            .buttonStyle(.plain)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
            .popover(isPresented: $showHelpOverlay, arrowEdge: .bottom) {
                HelpPopoverContent()
            }
        }
    }

    private func triggerSleep() {
        isSleepRunning = true
        sleepProgress = "Starting..."
        Task {
            do {
                let _ = try await APIClient.shared.triggerSleep()
                while true {
                    try await Task.sleep(for: .seconds(2))
                    let status = try await APIClient.shared.fetchSleepStatus()
                    await MainActor.run {
                        sleepProgress = status.progress ?? "Running..."
                    }
                    if status.status == "idle" { break }
                }
                await graphVM.loadGraph()
                await nudgeVM.loadNudges()
                await clarificationVM.loadClarifications()
            } catch {
                print("Sleep cycle error: \(error)")
            }
            await MainActor.run {
                withAnimation(.spring(duration: 0.3)) {
                    isSleepRunning = false
                    sleepProgress = ""
                }
            }
        }
    }
}

// MARK: - Help Popover Content

struct HelpPopoverContent: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text("ABOUT THESE ACTIONS")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "moon.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(CicadaTheme.accent)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Sleep")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text("Processes imported conversations and consolidates them into your memory graph. For day-to-day usage with Claude Desktop or other MCP clients, Cicada handles consolidation automatically — you only need to trigger Sleep manually after bulk imports.")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "arrow.up.doc")
                    .font(.system(size: 14))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Upload")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text("Import conversation exports from Claude, ChatGPT, or Gemini. Drop a folder or pick individual JSON/HTML files. Uploaded conversations become episodes ready for the next Sleep cycle.")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 340)
        .background(CicadaTheme.surface)
    }
}
