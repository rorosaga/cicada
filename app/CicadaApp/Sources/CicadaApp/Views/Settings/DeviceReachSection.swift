import SwiftUI

/// G212 (owner 2026-10-29) — *Reach from your phone*, inside Settings → Devices' list card above *Pair a device*: one
/// state (a dot and one line, DR-51's status shape) and the one next step. Where the step is a command (serve the
/// backend to the person's own tailnet, or close a public funnel) it is shown as a command to copy (`CommandBox`,
/// DR-19). Owner 2026-10-29 ("Yes, one click", the dated amendment to G132 (c)): on the serve step *Run it for me*
/// runs exactly that shown command, and on a served address *Stop serving* runs that one mapping's off after a
/// confirmation that names it (the confirm Settings' other stops use; DR-40's `NeutralButton` and `TextButton`) — never
/// a funnel command, never `up`. *Check again* (a `TextButton`, DR-40) asks the backend to fetch this Mac's own
/// served address the way a phone would and names where it stopped. Read on appear with the check, so opening the page
/// is the person's ask; never polled. No new visual pattern: the row reuses `StatusDot`, `CommandBox` and the
/// settings caption type (DR-39's flat row, no fold).
struct DeviceReachSection: View {
    @State private var reach: DeviceReach?
    @State private var checking = false
    @State private var running = false
    @State private var confirmStop = false
    /// The sentence a click's command came back with when it did not do it; nil once it did.
    @State private var outcome: String?
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
                    if let action = DeviceReachText.action(reach) {
                        // Owner 2026-10-29, "Yes, one click": the command above (or, to stop, the one the dialog
                        // names) is exactly what runs — the backend builds it, the app sends only the action.
                        HStack(spacing: CicadaTheme.spacingSM) {
                            if action == .serve {
                                NeutralButton(title: Copy.DevicesPage.Reach.runIt, size: .compact) {
                                    Task { await run(.serve) }
                                }
                                .disabled(running)
                                .accessibilityIdentifier("devices.reach.serve")
                            } else {
                                TextButton(title: Copy.DevicesPage.Reach.stop, inline: true) { confirmStop = true }
                                    .disabled(running)
                                    .accessibilityIdentifier("devices.reach.stop")
                            }
                            if running { ProgressView().controlSize(.small) }
                        }
                    }
                    if let outcome {
                        Text(outcome)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }
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
            .confirmationDialog(Copy.DevicesPage.Reach.stopTitle, isPresented: $confirmStop) {
                Button(Copy.DevicesPage.Reach.stop, role: .destructive) { Task { await run(.stop) } }
            } message: {
                Text(Copy.DevicesPage.Reach.willRun(reach?.stopCommand ?? ""))
            }
        }
    }

    private func run(_ action: DeviceReachAction) async {
        running = true
        outcome = nil
        defer { running = false }
        do {
            let answer = try await APIClient.shared.runDeviceReach(action)
            if let fresh = answer.reach { reach = fresh }
            outcome = answer.ok ? nil : (answer.message ?? Copy.DevicesPage.Reach.runFailed)
        } catch {
            outcome = Copy.DevicesPage.Reach.runFailed
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

    /// What a click may run on this step (owner 2026-10-29): the `serve` step's serve, the `ready` step's off. Never
    /// on `unfunnel` (a funnel command is only ever copied) or any other step.
    static func action(_ reach: DeviceReach) -> DeviceReachAction? {
        switch reach.step {
        case "serve": reach.command == nil ? nil : .serve
        case "ready": reach.stopCommand == nil ? nil : .stop
        default: nil
        }
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
