import SwiftUI

// MARK: - Top Bar Controls (Sleep + Upload + Help)

/// Which popover the `?` button opens (G125 Task 7). Every page but Sleep
/// wants `.actions` ("what do Sleep/Upload do") unchanged since 2026-09-01;
/// the Sleep page itself hides Sleep/Upload entirely (R10 — the one
/// Consolidate control now lives in the study list's footer) and repoints
/// its own `?` at *How Cicada sleeps* instead.
enum HelpContent: Equatable {
    case actions
    case howSleepWorks
}

struct TopBarControls: View {
    @Environment(SleepViewModel.self) private var sleepVM

    @Binding var selectedTab: AppTab
    @Binding var showUploadOverlay: Bool
    /// R10: `false` on the Sleep page only — every other call site keeps the
    /// default so it compiles and renders unchanged.
    var showsSleep: Bool = true
    var showsUpload: Bool = true
    var help: HelpContent = .actions
    @State private var showHelpOverlay = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            // Sleep button — switches to the Sleep tab and (if idle) kicks
            // off a cycle. All polling / progress state lives in
            // SleepViewModel so there's exactly one loop app-wide.
            if showsSleep {
                Button {
                    Task { @MainActor in
                        withAnimation(.spring(duration: 0.25)) {
                            selectedTab = .sleep
                        }
                        if !sleepVM.isRunning {
                            await sleepVM.triggerManually()
                        }
                    }
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        if sleepVM.isRunning {
                            ProgressView()
                                .controlSize(.small)
                                .frame(width: 14, height: 14)
                        } else {
                            Image(systemName: "moon.fill")
                                .font(.system(size: 12))
                        }
                        Text(sleepVM.isRunning ? "Sleeping..." : "Sleep")
                            .font(.system(size: 12, weight: .medium))
                    }
                    .foregroundStyle(sleepVM.isRunning ? CicadaTheme.textTertiary : CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .help(sleepVM.status?.progress ?? "Run memory consolidation")
            }

            // Upload button
            if showsUpload {
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
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
            }

            // Help button — the same button, a different popover per `help`.
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
            .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .popover(isPresented: $showHelpOverlay, arrowEdge: .bottom) {
                switch help {
                case .actions: HelpPopoverContent()
                case .howSleepWorks: HowSleepWorksContent()
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
