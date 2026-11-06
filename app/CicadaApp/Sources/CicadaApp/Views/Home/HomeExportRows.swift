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
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.importWait(vendor))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                // The row's visible affordance, drawn as a text button's label (DR-40): the row itself is the button.
                Text(Copy.importSeeHow)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            .rowHoverFill(hovering: hovering)
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
    var onHaveFile: (() -> Void)? = nil

    @FocusState private var focused: Bool

    var body: some View {
        ExportWalkthroughSheet(vendor: vendor, onClose: onClose, onHaveFile: onHaveFile)
            .focusable()
            .focusEffectDisabled()
            .focused($focused)
            .onAppear { focused = true }
    }
}

/// ROR-126 (Rodrigo: "the little worm on Home shows it's waiting on the export, per provider") — one quiet line a
/// provider while an export is on its way, whether the person asked for it by hand or their agent did. The worm is the
/// small mood sprite, not the study room's illustration (DR-13), and the row is the wait's own: the provider's name,
/// when it was asked, *Choose a file…* once it arrives and the ✕. A request the agent could not carry out is not a wait
/// (`ExportAgentRules.waitingVendors`): that provider is back to its manual walkthrough.
struct HomeExportWaitStrip: View {
    @Environment(ExportWaitStore.self) private var waits
    @Environment(ExportAgentModel.self) private var agent
    @Environment(IntakeRouter.self) private var intake
    @Environment(Store.self) private var store

    var body: some View {
        let active = waits.active(bank: store.bank)
        let waiting = Set(ExportAgentRules.waitingVendors(waits: active, requests: agent.requests))
        let rows = active.filter { waiting.contains($0.vendor) }
        Group {
            if !rows.isEmpty {
                TimelineView(.periodic(from: .now, by: ExportWaits.refreshInterval)) { context in
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(rows) { wait in
                            HStack(spacing: CicadaTheme.spacingSM) {
                                BookwormView(state: .awake, pointSize: CicadaTheme.scaled(20))
                                    .accessibilityHidden(true)
                                Text(ExportWaits.wormLine(wait, now: context.date))
                                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                                Spacer(minLength: CicadaTheme.spacingSM)
                                NeutralButton(title: Copy.intakeChooseFile, size: .compact) {
                                    intake.present(from: wait.intakeOrigin(fallback: .onboardingRow))
                                }
                                IconButton(systemName: "xmark", help: Copy.reminderDismiss,
                                           accessibilityLabel: "\(Copy.reminderDismiss), \(ExportWaits.vendorTitle(wait.vendor))") {
                                    Task { await agent.stopWaiting(vendor: wait.vendor, waits: waits, bank: store.bank) }
                                }
                            }
                            .padding(.horizontal, CicadaTheme.scaled(10))
                            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
                        }
                    }
                }
            }
        }
        .task { await agent.refresh(waits: waits, bank: store.bank) }
    }
}

extension ExportWaits {
    /// "Waiting on your Claude export · requested 2 hours ago", recomputed on every render.
    static func wormLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.exportWormLine(vendorTitle(w.vendor), requested: relative(w.requestedAt, now: now, locale: locale))
    }
}
