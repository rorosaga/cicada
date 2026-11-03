import AppKit
import SwiftUI

/// G95 (2026-11-03) — the Meeting recorders section's own control: add Hex's Markdown folder, or any folder of meeting
/// transcripts. The app reads the folder (G133: a bookmark, FSEvents, the bytes of changed files posted); the backend
/// parses each file into one meeting, its own date, every line its speaker's (`meeting_transcripts`).
///
/// DR-40: the row's verb is a compact `NeutralButton`, the sheet's one primary action is *Look inside*, then *Start
/// watching*. DR-33 / R-HS16: a sheet, never a popover. DR-38: under the source detail's head the mark and name are
/// already on screen, so the row says only how and whose words.
struct AddMeetingFolderRow: View {
    /// `"hex"` for Hex's own folder, nil for any recorder's.
    let recorder: String?
    @State private var picked: PickedFolder?
    @State private var refused: String?

    private var isHex: Bool { recorder == SourceCatalog.hexId }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(isHex ? Copy.Catalog.hexHow : Copy.Catalog.meetingFolderHow)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(Copy.Catalog.meetingWords)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                if let refused {
                    WarningLine(text: refused, warning: true)
                }
            }
            Spacer()
            NeutralButton(title: isHex ? Copy.Catalog.addHexFolder : Copy.Catalog.addFolder, size: .compact) { pick() }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .sheet(item: $picked) { picked in
            AddMeetingFolderSheet(url: picked.url, recorder: recorder) { self.picked = nil }
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = isHex ? Copy.Catalog.hexPanel : Copy.Catalog.meetingFolderPanel
        panel.prompt = Copy.SearchFiles.choose
        // Open in the Hex meetings folder (Hex's own setting, else its default) when it is there.
        let hexFolder = LocalSourceWatcher.hexMeetingsFolder()
        if isHex, FileManager.default.fileExists(atPath: hexFolder.path) {
            panel.directoryURL = hexFolder
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        refused = nil
        // The intake's refused roots: a watched folder's bytes are posted on every change, so a folder under
        // `~/.claude`, `~/.codex` or `~/.cicada` is never watched.
        if let refusal = IntakeRouter.refusedRoot(of: [url]) {
            refused = refusal.panelText
            return
        }
        picked = PickedFolder(url: url)
    }
}

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
