import SwiftUI

// MARK: - Top Bar Controls (Help; Sleep + Upload are opt-in seams — Track P R1)

/// Which popover the `?` button opens (G125 Task 7). Track P: the audit
/// removed the Sleep and Upload buttons from every page (R1), so "About
/// these actions" no longer had any actions to describe — `.actions` became
/// `.aboutCicada`, one paragraph per half of Awake/Sleep, true on every page
/// it renders on. The Sleep page keeps its own page-specific explainer
/// (R10 — the one Consolidate control lives in the study list's footer).
enum HelpContent: Equatable {
    case aboutCicada
    case howSleepWorks
}

struct TopBarControls: View {
    @Environment(SleepViewModel.self) private var sleepVM

    @Binding var selectedTab: AppTab
    @Binding var showUploadOverlay: Bool
    /// Track P R1 — the audit resolves by REMOVING: a cycle starts on the
    /// Sleep page (G125 R10 made that the one Consolidate control) and the
    /// menu-bar bookworm offers "Run Sleep" globally. Both flags survive as
    /// an opt-in seam rather than being deleted, because
    /// `Views/Sleep/SleepView.swift` passes them explicitly and a page added
    /// later may earn one back — but the DEFAULT is now the policy, so a
    /// page added later inherits "`?` only".
    var showsSleep: Bool = false
    /// Final review F1 — `showsUpload` is default-false but NOT unused:
    /// `FeedView` opts back in. "A one-shot import lives behind the Feed's
    /// `+` and ⌘N" (CLAUDE.md's Integrations rule) covers
    /// `UploadMode.conversations` only; `UploadMode.project` — an export
    /// imported into a chosen or newly created memory bank — has no
    /// `AddSourceTile`, and `UploadOverlay` is also the only writer of
    /// `Store.intakeInFlight` (G125 R2's `.reading` mascot). A default flip
    /// must not delete a capability that has no replacement.
    var showsUpload: Bool = false
    var help: HelpContent = .aboutCicada
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
                                .font(CicadaTheme.font(size: 12))
                        }
                        Text(sleepVM.isRunning ? "Sleeping..." : "Sleep")
                            .font(CicadaTheme.font(size: 12, weight: .medium))
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
                            .font(CicadaTheme.font(size: 12))
                        Text("Upload")
                            .font(CicadaTheme.font(size: 12, weight: .medium))
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
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 32, height: 28)
            }
            .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .popover(isPresented: $showHelpOverlay, arrowEdge: .bottom) {
                switch help {
                case .aboutCicada: AboutCicadaPopover()
                case .howSleepWorks: HowSleepWorksContent()
                }
            }
        }
    }

}

// MARK: - About Cicada Popover

/// The `?` popover on Graph, Clusters and Feed. Track P rewrote it: the old
/// two rows described the Sleep and Upload buttons this audit deleted, and
/// both sentences were false anyway — capture was pitched as something MCP
/// clients do (G105 replaced that with the harness's own Stop hook, which
/// cannot be skipped by a model declining to call a tool), and consolidation
/// was described as automatic when a fresh install's schedule is `manual`.
/// The two rows now name the two halves of Awake/Sleep instead of two
/// buttons, so the popover stays true on every page that renders it.
struct AboutCicadaPopover: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text("ABOUT CICADA")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(CicadaTheme.font(size: 14))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Capture")
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text(Copy.aboutCicadaCapture)
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "moon.fill")
                    .font(CicadaTheme.font(size: 14))
                    .foregroundStyle(CicadaTheme.accent)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Sleep")
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text(Copy.aboutCicadaSleep)
                        .font(CicadaTheme.font(size: 11))
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
