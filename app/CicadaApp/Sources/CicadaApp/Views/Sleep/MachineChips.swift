import SwiftUI

/// The Sleep page's machines, as one quiet row at the top of the words beside the room (owner 2026-11-24: "maybe the
/// connected machines can go at the top with the status light or something, and to quickly filter what comes from
/// where"). One chip per machine: a 7 pt light, its name — with a small house after it while it is the memory's home —
/// and what waits from it in tertiary tabular digits. A click narrows the page (Queue and Past sleeps) to that machine;
/// the selected chip again shows every machine. Single-select; selected is the selected-row fill and the strong ring,
/// never the accent. The light is never alone: `.help` and the VoiceOver label say it in words (`MachinesStrip.help`).
/// Drawn only with two machines or more — one machine has nothing to choose between.
struct MachineChipsView: View {
    let machines: [MachineStatus]
    let selected: String?
    let select: (MachineStatus?) -> Void

    var body: some View {
        if machines.count > 1 {
            // Names first; when the row cannot hold them (a narrow column, many machines) lights and counts, the
            // selected chip keeping its name — every chip's name is in its `.help` and its VoiceOver label.
            ViewThatFits(in: .horizontal) {
                row(compact: false)
                row(compact: true)
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(Copy.Machines.chipsLabel)
        }
    }

    private func row(compact: Bool) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ForEach(machines) { machine in
                MachineChip(machine: machine, machines: machines, isSelected: selected == machine.id,
                            compact: compact && selected != machine.id) {
                    select(selected == machine.id ? nil : machine)
                }
            }
        }
    }
}

struct MachineChip: View {
    let machine: MachineStatus
    let machines: [MachineStatus]
    let isSelected: Bool
    var compact = false
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static func lightColor(_ light: MachinesStrip.Light) -> Color {
        switch light {
        case .ok: CicadaTheme.success
        case .attention: CicadaTheme.warning
        case .quiet: CicadaTheme.textTertiary
        }
    }

    var body: some View {
        let help = MachinesStrip.help(machine, in: machines)
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Circle()
                    .fill(Self.lightColor(MachinesStrip.light(machine)))
                    .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
                    .accessibilityHidden(true)
                if !compact {
                    Text(MachinesStrip.displayName(machine))
                        .font(CicadaTheme.metaMediumFont)
                        .foregroundStyle(isSelected || hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: CicadaTheme.scaled(150))
                        .fixedSize(horizontal: true, vertical: false)
                    if MachinesStrip.isHome(machine, in: machines) {
                        Image(systemName: "house")
                            .font(CicadaTheme.font(size: 10, weight: .medium))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .accessibilityHidden(true)
                    }
                }
                if let count = MachinesStrip.chipCount(machine) {
                    Text(UsageFormat.count(count))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(9))
            .frame(height: CicadaTheme.scaled(26))
            .softCard(shape: .block, inset: .none, hovering: hovering, selected: isSelected)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .help(isSelected ? "\(help). \(Copy.Machines.showEveryMachine)" : help)
        .accessibilityLabel(isSelected ? Copy.Machines.chipSelected(help) : help)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

/// How a waiting card names the machine it came from (`MachinesStrip.originName`): set on the Queue's list while no
/// machine is the filter and there are two or more, read by `EpisodeCard` for its meta line; nothing by default.
private struct EpisodeMachineNameKey: EnvironmentKey {
    static let defaultValue: (EpisodeQueueItem) -> String? = { _ in nil }
}

extension EnvironmentValues {
    var episodeMachineName: (EpisodeQueueItem) -> String? {
        get { self[EpisodeMachineNameKey.self] }
        set { self[EpisodeMachineNameKey.self] = newValue }
    }
}
