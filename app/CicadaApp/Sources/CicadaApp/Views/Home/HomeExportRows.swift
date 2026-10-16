import SwiftUI

/// Owner 2026-10-14 ("the How to Export button … is very hard to click"; Home review #1) — one vendor's export ask on
/// Home, in onboarding's provider-row grammar (`ImportPage.providerRow`): a 36 pt row with the vendor's real mark, its
/// name in 13 medium (DR-16: never semibold), how long the export takes, and "See how ›". **The whole row is the
/// button** (DR-48: a `bgHover` fill on hover); it opens the drawn walkthrough (`ExportWalkthroughSheet`), which holds
/// *Open … export page* (its one primary) and *Remind me* — so the row carries one target instead of three plus an
/// 11 pt disclosure. The vendor's name appears only on its own row (provider-neutral copy).
struct ExportVendorRow: View {
    let vendor: ChatVendor
    let onSeeHow: (ChatVendor) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button { onSeeHow(vendor) } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                VendorMark(vendor: vendor, size: CicadaTheme.scaled(16)).markHover(hovering: hovering)
                Text(vendor.title)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.importWait(vendor))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                // The row's visible affordance, drawn as a text button's label (DR-40): the row itself is the button.
                Text(Copy.importSeeHow)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgHover : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.homeSeeHowHelp(vendor.title))
        .accessibilityLabel(Copy.homeSeeHowHelp(vendor.title))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// Review #11 — an export the person is waiting on. It leads with what to look for ("Check your email for the Claude
/// link · requested 2 hours ago", 12 pt meta — DR-16, a line someone needs is never caption), then *Choose a file…* and
/// the ×. It sits above the vendors still to ask, never in their place.
struct ExportWaitRow: View {
    let wait: ExportWait
    let now: Date
    let onChoose: () -> Void
    let onStop: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            VendorMark(origin: ChatVendor(rawValue: wait.vendor)?.origin, size: CicadaTheme.scaled(16))
            Text(ExportWaits.homeLine(wait, now: now))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.intakeChooseFile, size: .compact, action: onChoose)
            IconButton(systemName: "xmark", help: Copy.reminderDismiss,
                       accessibilityLabel: "\(Copy.reminderDismiss), \(ExportWaits.vendorTitle(wait.vendor))",
                       action: onStop)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}

extension ExportWaits {
    /// Home's wait line (review #11): what to look for first, then when it was asked. Recomputed on every render.
    static func homeLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.homeWaitLine(vendorTitle(w.vendor), requested: relative(w.requestedAt, now: now, locale: locale))
    }
}

/// The walkthrough over Home: the same `ExportWalkthroughSheet` onboarding presents (F-03, R-OB21), on its own scrim.
/// It takes key focus while it shows, so Esc closes it rather than clearing Home's field underneath.
struct HomeWalkthroughLayer: View {
    let vendor: ChatVendor
    let onClose: () -> Void

    @FocusState private var focused: Bool

    var body: some View {
        ExportWalkthroughSheet(vendor: vendor, onClose: onClose)
            .focusable()
            .focusEffectDisabled()
            .focused($focused)
            .onAppear { focused = true }
    }
}
