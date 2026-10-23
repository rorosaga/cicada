import AppKit
import SwiftUI

/// G219 — the Reminders row's one line, pure (`RemindersReaderTests`). `CalendarRowText`'s rules: the time in full
/// words, every count through `UsageFormat.count`, the backend's own `lastError` over a stale success.
enum RemindersRowText {
    static func line(_ status: RemindersReader.Status, channel: SourceChannel?, now: Date,
                     locale: Locale = .autoupdatingCurrent) -> String {
        switch status {
        case .off: return Copy.remindersOff
        case .denied: return Copy.remindersDenied
        case .noLists: return Copy.remindersNoLists
        case .syncing: return Copy.calendarSyncing
        case .failed(let why): return why
        case .synced(let at, let reminders):
            if let error = channel?.lastError, !error.isEmpty { return error }
            let relative = RelativeDateTimeFormatter()
            relative.unitsStyle = .full
            relative.dateTimeStyle = .named
            relative.locale = locale
            return Copy.remindersSynced(relative.localizedString(for: at, relativeTo: now), reminders: reminders,
                                        locale: locale)
        }
    }

    static func isProblem(_ status: RemindersReader.Status, channel: SourceChannel?) -> Bool {
        switch status {
        case .failed: return true
        case .off, .denied, .noLists: return false
        default: return channel?.lastError?.isEmpty == false
        }
    }
}

/// G219 — Reminders on the Sources page → This Mac: the lists the person ticks, read by the APP through EventKit
/// (`RemindersReader`) only after Connect, one way. `CalendarRow`'s layout (DR-40 `NeutralButton(size: .compact)`,
/// Disconnect behind a confirmation), then the list picker once connected: one tick per list, nothing pre-ticked, and
/// beside every list, ticked or not, "Others add to it", so a shared list is never read as the person's own words.
/// The mark is the installed Reminders app's own icon (DR-52; Apple's marks are never committed).
struct RemindersRow: View {
    let channel: SourceChannel?
    @Environment(RemindersReader.self) private var reader
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var confirmStop = false

    static let channelId = RemindersReader.channel
    /// System Settings → Privacy & Security → Reminders.
    static let privacyURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Reminders")!

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            row
            if reader.isEnabled, reader.status != .denied { picker }
        }
        .confirmationDialog(Copy.remindersStopTitle, isPresented: $confirmStop) {
            Button(Copy.calendarStop, role: .destructive) { reader.disconnect() }
            Button(Copy.cancelAction, role: .cancel) {}
        } message: {
            Text(Copy.remindersStopDetail)
        }
        .task { await reader.refreshLists() }
    }

    private var row: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if !headShown {
                LogoImage.platformTile(name: "",
                                       bundleId: OriginIconography.appBundleId(for: Self.channelId),
                                       size: CicadaTheme.scaled(28),
                                       systemFallback: OriginIconography.symbol(for: Self.channelId))
            }
            VStack(alignment: .leading, spacing: 2) {
                if !headShown {
                    Text(Copy.remindersTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                Text(RemindersRowText.line(reader.status, channel: channel, now: Date()))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(RemindersRowText.isProblem(reader.status, channel: channel)
                                     ? CicadaTheme.danger : CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            actions
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    @ViewBuilder
    private var actions: some View {
        switch reader.status {
        case .off:
            connectButton
        case .denied:
            NeutralButton(title: Copy.openPrivacySettings, size: .compact) { NSWorkspace.shared.open(Self.privacyURL) }
            connectButton
        case .syncing:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact, isDisabled: true,
                          disabledHelp: Copy.calendarSyncing) {}
            disconnectButton
        case .noLists:
            disconnectButton
        case .synced, .failed:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact) { Task { await reader.syncNow() } }
            disconnectButton
        }
    }

    private var connectButton: some View {
        NeutralButton(title: Copy.calendarConnect, size: .compact) { Task { await reader.connect() } }
    }

    private var disconnectButton: some View {
        NeutralButton(title: Copy.calendarDisconnect, size: .compact) { confirmStop = true }
    }

    private var picker: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.remindersListsHeader).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            ForEach(reader.available) { list in
                HStack(spacing: CicadaTheme.spacingMD) {
                    Toggle(isOn: Binding(get: { reader.ticked.contains(list.id) },
                                         set: { on in Task { await reader.setTicked(list.id, on) } })) {
                        Text(list.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    .toggleStyle(.checkbox)
                    Spacer()
                    // Offered before the tick (review of #455): a shared list's first read is never stored as the
                    // person's own words, because the choice can be made before anything is read.
                    Toggle(isOn: Binding(get: { reader.sharedLists.contains(list.id) },
                                         set: { on in Task { await reader.setShared(list.id, on) } })) {
                        Text(Copy.remindersShared).font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .toggleStyle(.checkbox)
                    .help(Copy.remindersSharedHelp)
                }
            }
            Text(Copy.remindersReads).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
    }
}
