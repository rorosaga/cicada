import AppKit
import SwiftUI

/// "Don't have one yet?" — one vendor's mark, what you get, the export page,
/// the steps (none of them "unzip" — the intake takes the .zip), and, Track I
/// part b (design §5.5, R-IB22), *Remind me*. Moved out of `IntakePanel` so the
/// panel and Getting started show the same row.
///
/// Every host is on the main window, which carries both `ExportWaitStore` and
/// `Store`. The notification permission is asked only from the delay menu —
/// the person's own act — and a denial still records the wait, so the row
/// says where the reminder waits instead of dropping it.
struct ExportAskRow: View {
    let vendor: ChatVendor
    let startsOpen: Bool
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store
    @State private var hovering = false
    @State private var showSteps = false
    @State private var denied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                VendorMark(vendor: vendor, size: CicadaTheme.scaled(22)).markHover(hovering: hovering)
                VStack(alignment: .leading, spacing: 2) {
                    Text(vendor.title).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                    Text(vendor.walkthrough.summary).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                Spacer()
                Button { NSWorkspace.shared.open(vendor.walkthrough.exportURL) } label: {
                    Label(Copy.intakeOpenExportPage, systemImage: "arrow.up.right.square")
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("\(Copy.intakeOpenExportPage), \(vendor.title)")
                Menu {
                    ForEach(ReminderDelay.allCases) { delay in
                        Button(delay.label) {
                            Task { denied = !(await waits.remind(vendor: vendor.rawValue, bank: store.bank, delay: delay)) }
                        }
                    }
                } label: {
                    Label(Copy.reminderRemindMe, systemImage: "bell")
                }
                .menuStyle(.borderedButton)
                .fixedSize()
                .accessibilityLabel("\(Copy.reminderRemindMe), \(vendor.title)")
            }
            if denied {
                Text(Copy.reminderNotificationsOff)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            DisclosureGroup(isExpanded: $showSteps) {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(vendor.walkthrough.steps.enumerated()), id: \.offset) { i, step in
                        Text("\(i + 1). \(step)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
            } label: {
                Text(Copy.intakeHowToGet).font(CicadaTheme.captionFont)
            }
        }
        .onHover { hovering = $0 }
        .onAppear { showSteps = startsOpen }
    }
}

/// The Welcome's compact twin of `ExportAskRow` (design §4.1.5, W12): one menu per
/// vendor, labelled with its real mark and name, holding *Open export page* and
/// the reminder delays — three menus fit on the card where three rows would not.
struct ExportAskMenu: View {
    let vendor: ChatVendor
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store
    /// Reported up so the Welcome can say where a refused reminder waits.
    var onDenied: () -> Void = {}

    var body: some View {
        Menu {
            Button { NSWorkspace.shared.open(vendor.walkthrough.exportURL) } label: {
                Label(Copy.intakeOpenExportPage, systemImage: "arrow.up.right.square")
            }
            Section(Copy.reminderRemindMe) {
                ForEach(ReminderDelay.allCases) { delay in
                    Button(delay.label) {
                        Task {
                            if !(await waits.remind(vendor: vendor.rawValue, bank: store.bank, delay: delay)) { onDenied() }
                        }
                    }
                }
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                VendorMark(vendor: vendor, size: CicadaTheme.scaled(16))
                Text(vendor.title).font(CicadaTheme.captionFont)
            }
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .accessibilityLabel("\(Copy.welcomeAskForOne), \(vendor.title)")
    }
}

/// F-03's footer (R-OB21): the *Remind me* half of `ExportAskMenu`, alone — the page is the sheet's primary.
struct ExportReminderMenu: View {
    let vendor: ChatVendor
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store
    @State private var denied = false

    var body: some View {
        Menu(Copy.reminderRemindMe) {
            ForEach(ReminderDelay.allCases) { delay in
                Button(delay.label) {
                    Task { if !(await waits.remind(vendor: vendor.rawValue, bank: store.bank, delay: delay)) { denied = true } }
                }
            }
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(denied ? Copy.reminderNotificationsOff : Copy.reminderRemindMe)
    }
}

extension ExportWait {
    /// Where a wait's *Choose a file…* or drop says it came from: the reminder's
    /// vendor, or `fallback` when a stored vendor is not one this build names.
    func intakeOrigin(fallback: IntakeOrigin) -> IntakeOrigin {
        ChatVendor(rawValue: vendor).map { .reminder($0) } ?? fallback
    }
}
