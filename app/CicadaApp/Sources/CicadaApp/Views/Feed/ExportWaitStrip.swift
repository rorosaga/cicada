import SwiftUI

/// Track I part b (design §5.5, R-IB22) — the text twin of an export reminder, at the head of Sleep › Saved (the
/// Feed's list, where it stood until the Feed folded into Sleep, 2026-10-16): it needs no notification permission, so
/// a person who said no to notifications still sees who they are waiting on. Home's Getting started shows the same
/// waits only while its card is up and no chat was dropped yet; this strip is where a graduated person still sees one,
/// can stop it, and can drop the export on it. Each row is itself a drop
/// target into the one intake (`accept(urls:from: .reminder(vendor))`), so the
/// export lands where the reminder said to drop it. A drop that sniffs as that
/// vendor clears the wait (`IntakeRouter.onVendorSniffed`); ✕ clears it by hand.
///
/// Inside a one-minute `TimelineView` so "requested 2 hours ago" stays true on
/// a page left open — the time is recomputed, never stored.
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
            // The caller insets it like the Videos strip, so it lines up with the rows under it.
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
