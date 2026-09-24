import AppKit
import SwiftUI

/// G154 (round 4) — "Contacts" in Settings → Integrations → Calendars, contacts & feeds: the Mac's address book, read
/// by the app (`ContactsReader`) only after Connect, enriching the people Cicada already knows. Laid out like
/// `CalendarRow`'s actions (DR-40 `NeutralButton`s, Disconnect behind a confirmation) on a `SourceRow`, so it says
/// "Last synced …" and shows an × while it runs. The mark is the installed Contacts app's own icon (DR-52).
struct ContactsRow: View {
    let channel: SourceChannel?
    @Environment(ContactsReader.self) private var reader
    @Environment(SyncActivity.self) private var activity
    @State private var confirmStop = false

    /// System Settings → Privacy & Security → Contacts.
    static let privacyURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Contacts")!

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            SourceRow(model: ContactsRowText.model(reader.status, channel: channel,
                                                   run: activity.run(for: ContactsReader.channel)),
                      now: context.date, onCancel: { activity.cancel(ContactsReader.channel) }) { actions }
        }
        .settingsRow(.contactsApp)
        .confirmationDialog(Copy.contactsStopTitle, isPresented: $confirmStop) {
            Button(Copy.contactsStop, role: .destructive) { reader.disconnect() }
            Button(Copy.cancelAction, role: .cancel) {}
        } message: {
            Text(Copy.contactsStopDetail)
        }
    }

    @ViewBuilder
    private var actions: some View {
        switch reader.status {
        case .off:
            NeutralButton(title: Copy.contactsConnect, size: .compact) { Task { await reader.connect() } }
        case .denied:
            NeutralButton(title: Copy.openPrivacySettings, size: .compact) { NSWorkspace.shared.open(Self.privacyURL) }
            NeutralButton(title: Copy.contactsConnect, size: .compact) { Task { await reader.connect() } }
        case .syncing:
            EmptyView()
        case .watching, .empty, .failed:
            NeutralButton(title: Copy.contactsSyncNow, size: .compact) { Task { await reader.syncNow() } }
            NeutralButton(title: Copy.contactsDisconnect, size: .compact) { confirmStop = true }
        }
    }
}

/// The Contacts row, pure.
enum ContactsRowText {
    static func model(_ status: ContactsReader.Status, channel: SourceChannel?, run: SyncActivity.Run?) -> SourceRowModel {
        var model = SourceRowModel(id: ContactsReader.channel, origin: "contacts-local", title: Copy.contactsTitle,
                                   meta: Copy.contactsMeta)
        switch status {
        case .off: model.line = Copy.contactsOff
        case .denied: model.line = Copy.contactsDenied
        case .empty: model.line = Copy.contactsEmpty
        default: model.line = channel.flatMap { SourceRowText.countLine($0) }
        }
        if let run {
            model.status = .syncing(detail: run.detail, fraction: run.fraction, cancellable: run.cancellable)
        } else if case .failed(let why) = status {
            model.status = .problem(why)
        } else if status == .off || status == .denied {
            model.status = .idle
        } else {
            model.status = SourceRowText.status(channel: channel, watch: nil, run: nil)
        }
        return model
    }
}
