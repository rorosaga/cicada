import SwiftUI

/// G132 phase 2 (ruling 51a; owner 2026-10-29: "Sleep page on the app should show the selected device running
/// consolidation and you should be able to easily switch") — under the room, only while this memory is shared with
/// another device AND there is something to do or to say. Since the machine chips (owner 2026-11-24) the chips say who
/// runs consolidation (the house), who is online and how far behind each copy is; this keeps only what a chip cannot:
/// an inline "Make this the home" on a device that can be, "Take over on this computer…" for a lost home, and what the
/// backend says in words (moving, set aside, a refusal) as plain lines. A pick asks once in a confirmation (the native
/// dialog, as Settings → Devices' revoke does) and that is the hand-off; a take-over's confirmation shows how far behind
/// this copy is first. Existing patterns only: inline `TextButton`s (DR-40, DR-41: disabled while busy), plain lines
/// with no card (DR-37, DR-59); nothing drawn when nothing is shared or nothing is to be done (DR-81); no new motion.
struct HomeStripView: View {
    let model: HomeStripModel
    @State private var pendingMove: HomeOverview.Device?

    var body: some View {
        if model.isShown, let overview = model.overview,
           HomeStrip.hasNews(overview, movingLine: model.movingLine, problem: model.problem, isMoving: model.isMoving) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                // The machines — who runs Sleep, who is online, how far behind — are the chips' to say. What is left is
                // what a chip cannot: moving the home, taking over, and the backend's own words.
                ForEach(HomeStrip.movable(overview, isMoving: model.isMoving)) { device in
                    row(device)
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

    /// One device that can take the home: its name and the one act, "Make this the home".
    private func row(_ device: HomeOverview.Device) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(device.name)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            TextButton(title: Copy.MemoryHome.makeHome, help: Copy.MemoryHome.makeHomeHelp(device.name), inline: true) {
                pendingMove = device
            }
            .disabled(model.busy)
        }
        .accessibilityElement(children: .combine)
    }
}
