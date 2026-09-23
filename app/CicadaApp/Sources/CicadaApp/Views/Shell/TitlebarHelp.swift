import SwiftUI

// MARK: - The titlebar's ? (R-DS18)

/// Which popover the titlebar's `?` opens — Sleep explains how Cicada sleeps, every other page
/// what Cicada is (R-DS18). Track P: the audit removed the Sleep and Upload buttons from every
/// page (R1), so "About these actions" no longer had any actions to describe — `.actions`
/// became `.aboutCicada`, one paragraph per half of Awake/Sleep, true on every page it renders
/// on. The Sleep page keeps its own page-specific explainer (G125 R10).
enum HelpContent: Equatable {
    case aboutCicada
    case howSleepWorks

    static func page(_ tab: AppTab) -> HelpContent { tab == .sleep ? .howSleepWorks : .aboutCicada }
}

/// The page's `?` — the titlebar's rightmost control, one per window, answering for the visible
/// page (DR-23, Track P). It replaced a `TopBarControls` floated by four pages at four slightly
/// different offsets.
struct TitlebarHelpButton: View {
    let content: HelpContent
    @State private var showing = false

    var body: some View {
        IconButton(systemName: "questionmark.circle", help: Copy.helpForThisPage, size: .titlebar) { showing.toggle() }
            .popover(isPresented: $showing, arrowEdge: .bottom) {
                switch content {
                case .aboutCicada: AboutCicadaPopover()
                case .howSleepWorks: HowSleepWorksContent()
                }
            }
    }
}

// MARK: - About Cicada Popover

/// The titlebar `?`'s popover on every page but Sleep (R-DS18). Track P rewrote it: the old
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
            SectionLabel("About Cicada")

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
                    // DR-5: the accent is never decorative.
                    .foregroundStyle(CicadaTheme.textSecondary)
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
