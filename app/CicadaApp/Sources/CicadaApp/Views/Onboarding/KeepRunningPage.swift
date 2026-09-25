import AppKit
import SwiftUI

/// F-06 (G145; owner decision 6: "switched on and off in settings, for menu bar and open at login") — the same
/// switches as Settings → General (F-10): Open Cicada at login (`LoginItemService`, the quiet start said truthfully,
/// R-OB18; the approval pointer only while macOS waits; an unsigned build that macOS never keeps says so), Show in
/// menu bar, and Keep memory working (`BackgroundServiceButton`, the command shown first). Nothing is switched on for
/// the person (R-OB14): each switch shows its real state and changes only on a click. No drawn System Settings (the
/// F-03 rule) — a breadcrumb line and *Open Login Items*. The lists are `KeepRunning`'s. DR-13, DR-19, DR-40.
struct KeepRunningPage: View {
    @Environment(LoginItemService.self) private var loginItems
    @Environment(BackendAgentService.self) private var backendAgent
    @AppStorage(MenuBarPreference.defaultsKey) private var showsMenuBar = true

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.keepRunningTitle, subline: Copy.keepRunningSubline)
            VStack(spacing: 0) {
                switchRow(symbol: "power", title: Copy.openAtLogin,
                          detail: loginItems.state.detail(menuBarVisible: showsMenuBar),
                          isOn: Binding(get: { loginItems.requested }, set: { loginItems.setEnabled($0) }))
                SettingsDivider()
                switchRow(symbol: "menubar.rectangle", title: Copy.showInMenuBar, detail: Copy.showInMenuBarDetail,
                          isOn: $showsMenuBar)
            }
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            OnboardingPointerLine(lead: Copy.keepRunningBothInSettings, section: .general,
                                  label: Copy.onboardingSettingsGeneral)
            if loginItems.requested {
                caption(Copy.keepRunningBackgroundItems)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                caption(Copy.keepRunningWhere)
                if loginItems.state.offersSettings {
                    TextButton(title: Copy.openLoginItems, help: Copy.openLoginItemsHelp) { loginItems.openSystemSettings() }
                }
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack {
                    Text(Copy.keepMemoryWorking).font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Spacer()
                    BackgroundServiceButton()
                }
                caption(Copy.backgroundDetail(backendAgent.state))
                if BackgroundServiceButton.showsCommand(backendAgent.state) {
                    CommandBox(command: backendAgent.display)
                }
            }
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                list(Copy.keepRunningWhileOpen, KeepRunning.whileOpen())
                list(Copy.keepRunningAfterQuit, KeepRunning.afterQuit(backgroundRunning: backendAgent.state == .running))
            }
        }
        // Reads only: the page shows what is, and sets nothing (R-OB14).
        .task { loginItems.refresh(); await backendAgent.refresh() }
        // The person may have just used System Settings → Login Items (R-FA7).
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            loginItems.refresh()
        }
    }

    private func switchRow(symbol: String, title: String, detail: String, isOn: Binding<Bool>) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: symbol).foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(20))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(title).font(CicadaTheme.font(size: 13, weight: .medium)).foregroundStyle(CicadaTheme.textPrimary)
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Toggle(title, isOn: isOn).toggleStyle(.switch).labelsHidden()
        }
        .padding(CicadaTheme.spacingMD)
    }

    private func caption(_ text: String) -> some View {
        Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func list(_ title: String, _ lines: [String]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(title)
            ForEach(lines, id: \.self) { line in
                Label(line, systemImage: "checkmark").font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }
}
