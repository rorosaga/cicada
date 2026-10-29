import SwiftUI

/// G212 (owner 2026-10-29) — *Reach from your phone*, inside Settings → Devices' list card above *Pair a device*: one
/// state (a dot and one line, DR-51's status shape) and the one next step. Where the step is a command (serve the
/// backend to the person's own tailnet, or close a public funnel) it is shown as a command to copy (`CommandBox`,
/// DR-19) — Cicada never runs it: the overlay is the person's (G132 (c)), and whether a click may run it waits on the
/// owner (report, "Needs the owner"). *Check again* (a `TextButton`, DR-40) asks the backend to fetch this Mac's own
/// served address the way a phone would and names where it stopped. Read on appear with the check, so opening the page
/// is the person's ask; never polled. No new visual pattern: the row reuses `StatusDot`, `CommandBox` and the
/// settings caption type (DR-39's flat row, no fold).
struct DeviceReachSection: View {
    @State private var reach: DeviceReach?
    @State private var checking = false
    /// When the backend has no reach route (an older one), the section draws nothing.
    @State private var unavailable = false

    var body: some View {
        if !unavailable {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.DevicesPage.Reach.title)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let reach {
                        StatusDot(word: DeviceReachText.word(reach), on: DeviceReachText.on(reach))
                    }
                }
                if let reach {
                    caption(DeviceReachText.line(reach))
                    if let command = reach.command { CommandBox(command: command) }
                    if reach.step == "install" {
                        SettingsHelpLink(url: Copy.DevicesPage.Reach.downloadURL,
                                         label: Copy.DevicesPage.Reach.getTailscale)
                            .font(CicadaTheme.captionFont)
                    }
                    if let checked = DeviceReachText.checkLine(reach) {
                        Text(checked)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(reach.check?.ok == true ? CicadaTheme.textSecondary : CicadaTheme.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextButton(title: checking ? Copy.DevicesPage.Reach.checking : Copy.DevicesPage.Reach.check,
                               inline: true) { Task { await load() } }
                        .disabled(checking)
                        .accessibilityIdentifier("devices.reach.check")
                    if checking { ProgressView().controlSize(.small) }
                }
            }
            .padding(CicadaTheme.spacingMD)
            .task { await load() }
        }
    }

    private func load() async {
        checking = true
        defer { checking = false }
        do {
            reach = try await APIClient.shared.fetchDeviceReach(check: true)
        } catch {
            if let detail = ConnectionModelText.detail(error), detail.code == 404 { unavailable = true }
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// The section's words from one answer, pure (tested): the dot, its word, the step's line and the check's line.
enum DeviceReachText {
    /// Green only when the address is served AND the live check passed (or has not run yet on a ready serve).
    static func on(_ reach: DeviceReach) -> Bool {
        reach.step == "ready" && reach.check?.ok != false
    }

    static func word(_ reach: DeviceReach) -> String {
        on(reach) ? Copy.Status.connected : Copy.Status.notConnected
    }

    static func line(_ reach: DeviceReach) -> String {
        if reach.step == "ready", let url = reach.url { return Copy.DevicesPage.Reach.readyAt(url) }
        return Copy.DevicesPage.Reach.step(reach.step)
    }

    /// Only for a served address: passed in so many ms, or where it stopped.
    static func checkLine(_ reach: DeviceReach) -> String? {
        guard reach.step == "ready", let check = reach.check else { return nil }
        if check.ok { return Copy.DevicesPage.Reach.ready }
        return Copy.DevicesPage.Reach.failed(check.failed ?? "")
    }
}
