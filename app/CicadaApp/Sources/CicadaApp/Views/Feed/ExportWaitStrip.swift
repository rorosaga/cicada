import SwiftUI

/// Track I part b (design §5.5, R-IB22) — the Feed's text twin of an export
/// reminder: it needs no notification permission, so a person who said no to
/// notifications still sees who they are waiting on. Each row is itself a drop
/// target into the one intake (`accept(urls:from: .reminder(vendor))`), so the
/// export lands where the reminder said to drop it. A drop that sniffs as that
/// vendor clears the wait (`IntakeRouter.onVendorSniffed`); ✕ clears it by hand.
///
/// Inside a one-minute `TimelineView` so "requested 2 hours ago" stays true on
/// a Feed left open — the time is recomputed, never stored.
struct ExportWaitStrip: View {
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store

    var body: some View {
        let active = waits.active(bank: store.bank)
        if !active.isEmpty {
            TimelineView(.periodic(from: .now, by: ExportWaits.refreshInterval)) { context in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(active) { WaitRow(wait: $0, now: context.date) }
                }
            }
            // The Feed's own column padding, the same as `ConnectedChannelsStrip`'s.
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingMD)
        }
    }
}

private struct WaitRow: View {
    let wait: ExportWait
    let now: Date
    @Environment(ExportWaitStore.self) private var waits
    @Environment(IntakeRouter.self) private var intake
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var targeted = false

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
        HStack(spacing: CicadaTheme.spacingSM) {
            VendorMark(origin: ChatVendor(rawValue: wait.vendor)?.origin, size: CicadaTheme.scaled(18))
            Text(ExportWaits.stripLine(wait, now: now))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            Text(Copy.reminderDropHere)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
            Spacer(minLength: CicadaTheme.spacingSM)
            Button { waits.remove(wait) } label: {
                Image(systemName: "xmark")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .iconHover()
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.reminderDismiss)
            .accessibilityLabel("\(Copy.reminderDismiss), \(ExportWaits.vendorTitle(wait.vendor))")
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .background(targeted ? CicadaTheme.meadowWash : CicadaTheme.surface, in: shape)
        .overlay(shape.strokeBorder(targeted ? CicadaTheme.meadow : CicadaTheme.border,
                                    style: StrokeStyle(lineWidth: 1, dash: [6, 4])))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: targeted)
        .onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
            IntakeDrop.load(providers) { urls in intake.accept(urls: urls, from: wait.intakeOrigin(fallback: .windowDrop)) }
            return true
        }
        .accessibilityElement(children: .combine)
    }
}
