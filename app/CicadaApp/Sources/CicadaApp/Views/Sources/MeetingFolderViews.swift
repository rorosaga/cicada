import AppKit
import SwiftUI

/// The words for a meeting folder's preview: how many meetings, and how many files hold none. Pure; tested.
enum MeetingFolderText {
    static func preview(_ r: FolderSyncResult, locale: Locale = .autoupdatingCurrent) -> String {
        let meetings = r.filesNew + r.filesChanged + r.filesUnchanged
        var line = "Found " + Copy.SearchFiles.meetings(meetings, locale: locale)
        let skipped = r.errors.filter { $0.reason == "not a meeting transcript" }.count
        if skipped > 0 {
            line += " · \(UsageFormat.count(skipped, locale: locale)) \(skipped == 1 ? "file holds" : "files hold") no transcript"
        }
        return line
    }
}

/// Name it, look inside (counts only), then start watching. Registered on *Look inside* so the preview has a folder
/// id; closing the sheet before *Start watching* removes that registration again — never a folder that was already
/// watched. A folder already watched as notes is refused by the backend (409, its words shown), never turned into one.
struct AddMeetingFolderSheet: View {
    let url: URL
    let recorder: String?
    let onDone: () -> Void
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var label: String
    @State private var folder: FolderRegistration?
    /// The folder was already watched before this sheet registered it (a re-pick): closing the sheet keeps it.
    @State private var existed = false
    @State private var preview: FolderSyncResult?
    @State private var busy = false
    @State private var message: String?

    init(url: URL, recorder: String?, onDone: @escaping () -> Void) {
        self.url = url
        self.recorder = recorder
        self.onDone = onDone
        _label = State(initialValue: url.lastPathComponent)
    }

    var body: some View {
        SettingsSheet(title: Copy.Catalog.addMeetingTitle, onClose: { Task { await cancel() } }) {
            Text(url.path)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.Folders.name)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                // DR-76 — a page's own sheet uses the app's one field.
                TextField("", text: $label)
                    .cicadaField(prompt: url.lastPathComponent, isEmpty: label.isEmpty)
                    .accessibilityLabel(Copy.Folders.name)
                    .disabled(folder != nil)
            }
            if let preview {
                Text(MeetingFolderText.preview(preview))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Catalog.meetingWords)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let message {
                WarningLine(text: message, warning: true)
            }
            HStack {
                Spacer()
                PrimaryActionButton(title: preview == nil ? Copy.SearchFiles.lookInside : Copy.SearchFiles.startWatching) {
                    Task { if preview == nil { await look() } else { await start() } }
                }
            }
        }
        .disabled(busy)
    }

    private func look() async {
        busy = true
        defer { busy = false }
        do {
            let known = Set(localSources.folders.map(\.id))
            let registered = try await localSources.addMeetingFolder(url: url, label: label, recorder: recorder)
            existed = known.contains(registered.id)
            folder = registered
            preview = try await localSources.preview(registered, root: url)
            message = nil
        } catch {
            message = AddSourceSheet.friendlyError(error)
        }
    }

    private func start() async {
        guard let folder else { return }
        await localSources.startWatching(folder)
        onDone()
    }

    private func cancel() async {
        // Only a registration this sheet made is undone: a folder that was already watched stays as it was.
        if let folder, !existed { try? await localSources.removeFolder(folder) }
        onDone()
    }
}
