import SwiftUI

/// G212 (owner D6: "refer to the mac … as its name") — under the room, each machine by its own name with a dot (green
/// while connected), how it connects and what of its waits; a click opens that machine's queue in Waiting below, a
/// second click shows every machine's again. Polled while the page shows (`GET /devices/status`, not a Store domain,
/// held in memory; a failed poll keeps the last answer — never blank).
struct MachinesStripView: View {
    let machines: [MachineStatus]
    let selected: String?
    let select: (MachineStatus?) -> Void

    var body: some View {
        if !machines.isEmpty {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: CicadaTheme.spacingLG) { buttons }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) { buttons }
            }
            .accessibilityElement(children: .contain)
        }
    }

    @ViewBuilder
    private var buttons: some View {
        ForEach(machines) { machine in
            let isOn = selected == machine.id
            Button {
                select(isOn ? nil : machine)
            } label: {
                HStack(spacing: CicadaTheme.scaled(6)) {
                    Circle()
                        .fill(machine.connected ? CicadaTheme.success : CicadaTheme.textTertiary)
                        .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
                    Text(MachinesStrip.line(machine))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(isOn ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                }
                .padding(.horizontal, CicadaTheme.scaled(8))
                .frame(height: CicadaTheme.scaled(26))
                .background(isOn ? CicadaTheme.bgSelected : Color.clear,
                            in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(isOn ? Copy.Machines.allMachines : Copy.Machines.openQueue(machine.name))
            .accessibilityLabel("\(MachinesStrip.line(machine)), "
                                + (machine.connected ? Copy.Machines.connected : Copy.Machines.notConnected))
            .accessibilityAddTraits(isOn ? .isSelected : [])
        }
    }
}
