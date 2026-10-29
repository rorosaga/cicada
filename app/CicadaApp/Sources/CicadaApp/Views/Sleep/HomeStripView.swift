import SwiftUI

/// G132 phase 2 (ruling 51a; owner 2026-10-29: "Sleep page on the app should show the selected device running
/// consolidation and you should be able to easily switch") — under the machines strip, only while this memory is
/// shared with another device: one line naming the device that runs consolidation (the home, which also keeps every
/// change in order — one concept) with its Sleep state, then every other device with a dot (green while online), its
/// name and how far behind its copy is, and an inline "Make this the home" on a device that can be. A pick asks once
/// in a confirmation (the native dialog, as Settings → Devices' revoke does) and that is the hand-off. A lost home
/// offers "Take over on this computer…", whose confirmation shows how far behind this copy is first. What the backend
/// says in words (moving, set aside) follows as plain lines. Existing patterns only: the strip's meta line and dot
/// (MachinesStripView), inline `TextButton`s (DR-40, DR-41: disabled while busy), plain lines with no card (DR-37,
/// DR-59); nothing drawn when nothing is shared and no disclosure (DR-81); no new motion.
struct HomeStripView: View {
    let model: HomeStripModel
    @State private var pendingMove: HomeOverview.Device?

    var body: some View {
        if model.isShown, let overview = model.overview, let home = overview.home {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(HomeStrip.homeLine(home))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                ForEach(overview.devices) { device in
                    row(device, overview: overview)
                }
                if overview.takeOver?.possible == true {
                    TextButton(title: Copy.MemoryHome.takeOver, help: Copy.MemoryHome.takeOverHelp, inline: true,
                               flushLeading: true) {
                        Task { await model.askTakeOver() }
                    }
                    .disabled(model.busy)
                }
                ForEach(Array(HomeStrip.lines(overview, movingLine: model.movingLine, problem: model.problem)
                                .enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .accessibilityElement(children: .contain)
            .confirmationDialog(Copy.MemoryHome.moveTitle(pendingMove?.name ?? ""),
                                isPresented: Binding(get: { pendingMove != nil },
                                                     set: { if !$0 { pendingMove = nil } }),
                                titleVisibility: .visible) {
                if let device = pendingMove {
                    Button(Copy.MemoryHome.move(device.name)) {
                        pendingMove = nil
                        Task { await model.makeHome(device) }
                    }
                }
                Button(Copy.MemoryHome.cancel, role: .cancel) { pendingMove = nil }
            } message: {
                Text(Copy.MemoryHome.moveMessage(pendingMove?.name ?? ""))
            }
            .confirmationDialog(Copy.MemoryHome.takeOverTitle,
                                isPresented: Binding(get: { model.preview != nil },
                                                     set: { if !$0 { model.cancelTakeOver() } }),
                                titleVisibility: .visible) {
                if let behind = model.preview?.behind {
                    // The number shown is captured here: the dialog's dismissal clears the preview before a Task runs.
                    Button(Copy.MemoryHome.takeOverConfirm, role: .destructive) {
                        Task { await model.takeOver(behind: behind) }
                    }
                }
                Button(Copy.MemoryHome.cancel, role: .cancel) { model.cancelTakeOver() }
            } message: {
                Text(model.preview?.text ?? "")
            }
        }
    }

    private func row(_ device: HomeOverview.Device, overview: HomeOverview) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Circle()
                .fill(device.online ? CicadaTheme.success : CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
            Text(HomeStrip.deviceLine(device))
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            if HomeStrip.offersMove(device, in: overview) && !model.isMoving {
                TextButton(title: Copy.MemoryHome.makeHome, help: Copy.MemoryHome.makeHomeHelp(device.name),
                           inline: true) {
                    pendingMove = device
                }
                .disabled(model.busy)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
