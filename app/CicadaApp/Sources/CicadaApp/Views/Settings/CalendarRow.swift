import AppKit
import SwiftUI

/// R-FA13 — the Calendar row's one line, pure (`CalendarReaderTests`). The time in full words, computed when read
/// (DR-58; never "2mo ago"), every count through `UsageFormat.count` (DR-21), and the backend's own `lastError` for the
/// `calendar-local` channel over a stale success.
enum CalendarRowText {
    static func line(_ status: CalendarReader.Status, channel: SourceChannel?, now: Date,
                     locale: Locale = .autoupdatingCurrent) -> String {
        switch status {
        case .off: return Copy.calendarOff
        case .denied: return Copy.calendarDenied
        case .syncing: return Copy.calendarSyncing
        case .failed(let why): return why
        case .synced(let at, let events):
            if let error = channel?.lastError, !error.isEmpty { return error }
            let relative = RelativeDateTimeFormatter()
            relative.unitsStyle = .full
            relative.dateTimeStyle = .named     // "now", never "in 0 seconds"
            relative.locale = locale
            return Copy.calendarSynced(relative.localizedString(for: at, relativeTo: now), events: events, locale: locale)
        }
    }

    /// The line reads as a problem when the reader failed or the backend recorded an error for the channel.
    static func isProblem(_ status: CalendarReader.Status, channel: SourceChannel?) -> Bool {
        if case .failed = status { return true }
        if case .denied = status { return false }
        if case .off = status { return false }
        return channel?.lastError?.isEmpty == false
    }
}

/// Round-4 D2 (R-FA11 … R-FA13) — "Calendar on this Mac" in Settings → Integrations → Feeds & calendars: every
/// calendar account the Calendar app holds, read by the APP through EventKit (`CalendarReader`) only after Connect.
/// The backend's `calendar-local` channel is rendered here and never as a second `IntegrationChannelRow`.
///
/// Laid out like `WisprFlowRow` (mark, title over line, the actions), but new, so it follows DESIGN_RULES rather than
/// its pre-D siblings: DR-40's `NeutralButton(size: .compact)` for every action, and Disconnect behind a confirmation
/// whose destructive role carries the danger colour. The mark is the installed Calendar app's own icon (DR-52) —
/// Apple's marks are never committed (Track L).
struct CalendarRow: View {
    let channel: SourceChannel?
    @Environment(CalendarReader.self) private var reader
    @State private var confirmStop = false

    /// C6's channel id, stamped by the backend track; the row that renders it and the lists that skip it share it.
    static let channelId = "calendar-local"

    /// System Settings → Privacy & Security → Calendars.
    static let privacyURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")!

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            LogoImage.platformTile(name: "",
                                   bundleId: OriginIconography.appBundleId(for: "calendar-local"),
                                   size: CicadaTheme.scaled(28),
                                   systemFallback: OriginIconography.symbol(for: "calendar-local"))
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.calendarAppTitle)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(CalendarRowText.line(reader.status, channel: channel, now: Date()))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CalendarRowText.isProblem(reader.status, channel: channel)
                                     ? CicadaTheme.danger : CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            actions
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.calendarApp)
        .confirmationDialog(Copy.calendarStopTitle, isPresented: $confirmStop) {
            Button(Copy.calendarStop, role: .destructive) { reader.disconnect() }
            Button(Copy.cancelAction, role: .cancel) {}
        } message: {
            Text(Copy.calendarStopDetail)
        }
    }

    @ViewBuilder
    private var actions: some View {
        switch reader.status {
        case .off:
            connectButton
        case .denied:
            // After the person turns access on there, Connect asks again and syncs; nothing re-reads on its own.
            NeutralButton(title: Copy.openPrivacySettings, size: .compact) {
                NSWorkspace.shared.open(Self.privacyURL)
            }
            connectButton
        case .syncing:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact, isDisabled: true,
                          disabledHelp: Copy.calendarSyncing) {}
            disconnectButton
        case .synced, .failed:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact) {
                Task { await reader.syncNow() }
            }
            disconnectButton
        }
    }

    private var connectButton: some View {
        NeutralButton(title: Copy.calendarConnect, size: .compact) {
            Task { await reader.connect() }
        }
    }

    private var disconnectButton: some View {
        NeutralButton(title: Copy.calendarDisconnect, size: .compact) { confirmStop = true }
    }
}
