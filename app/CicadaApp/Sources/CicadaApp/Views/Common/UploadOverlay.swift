import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - Upload History Entry

struct UploadHistoryEntry: Identifiable, Codable {
    let id: String
    let filename: String
    let provider: String
    let date: String
    let episodesCreated: Int
    let duplicatesSkipped: Int

    init(filename: String, provider: String, date: String, episodesCreated: Int, duplicatesSkipped: Int) {
        self.id = UUID().uuidString
        self.filename = filename
        self.provider = provider
        self.date = date
        self.episodesCreated = episodesCreated
        self.duplicatesSkipped = duplicatesSkipped
    }
}

// MARK: - Upload Overlay

enum UploadMode: String, CaseIterable {
    case conversations = "Conversations"
    case project = "Project import"
    case sources = "Saved media"
}

struct UploadOverlay: View {
    @Binding var isPresented: Bool
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(GraphViewModel.self) private var graphVM
    @State private var isDragOver = false
    @State private var isUploading = false
    @State private var uploadResult: String?
    @State private var errorMessage: String?
    @State private var mode: UploadMode = .conversations
    @State private var urlText = ""

    // M7 project-import target. nil = "new project" (creates `newBankName`);
    // otherwise an existing bank name.
    @State private var targetBank: String?
    @State private var newBankName = ""

    var body: some View {
        ZStack {
            // Dimmed background — tap to dismiss
            Color.black.opacity(0.4)
                .ignoresSafeArea()
                .onTapGesture {
                    if !isUploading {
                        withAnimation(.spring(duration: 0.3)) {
                            isPresented = false
                        }
                    }
                }

            // Upload box
            VStack(spacing: CicadaTheme.spacingLG) {
                Picker("", selection: $mode) {
                    ForEach(UploadMode.allCases, id: \.self) { m in
                        Text(m.rawValue).tag(m)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 280)
                .disabled(isUploading)
                .onChange(of: mode) { _, newMode in
                    uploadResult = nil
                    errorMessage = nil
                    if newMode == .project {
                        Task {
                            await banksVM.load()
                            if targetBank == nil { targetBank = banksVM.activeName }
                        }
                    }
                }

                // The same bookworm mascot as the menu bar: it chews
                // (`.digesting`) while ingesting, beams (`.happy`) on success,
                // and idles (`.awake`) otherwise. Reuses deriveBookwormState
                // semantics by passing the state directly.
                BookwormView(
                    state: mascotState,
                    pointSize: 72,
                    tint: isDragOver ? CicadaTheme.accent : CicadaTheme.textSecondary
                )
                .frame(height: 72)

                Text(titleText)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)

                if let result = uploadResult {
                    Text(result)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(Color(hex: 0x22C55E))
                        .multilineTextAlignment(.center)
                } else if let err = errorMessage {
                    Text(err)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(Color(hex: 0xEF4444))
                        .multilineTextAlignment(.center)
                } else if mode == .conversations {
                    Text("Drag and drop the folder here\nor click to select")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .multilineTextAlignment(.center)
                } else if mode == .project {
                    Text("Import a Claude, ChatGPT, or Gemini export\n(.json / .html / .zip) into a memory project")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .multilineTextAlignment(.center)
                } else {
                    Text("Drop a browser bookmarks export (HTML/JSON),\na Takeout file, an RSS/Atom feed (XML), or paste a URL below")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .multilineTextAlignment(.center)
                }

                if mode == .project {
                    bankTargetSelector
                }

                if mode == .sources {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "link")
                            .font(.system(size: 12))
                            .foregroundStyle(CicadaTheme.textTertiary)
                        TextField("https://…", text: $urlText)
                            .textFieldStyle(.plain)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .onSubmit { saveURL() }
                        Button("Save") { saveURL() }
                            .buttonStyle(.plain)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(urlText.isEmpty ? CicadaTheme.textTertiary : CicadaTheme.accent)
                            .disabled(urlText.isEmpty || isUploading)
                    }
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .frame(width: 340)
                }

                Button {
                    pickFilesOrFolder()
                } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "folder")
                        Text("Choose Files or Folder")
                    }
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.vertical, CicadaTheme.spacingMD)
                    .background(CicadaTheme.accent.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                }
                .buttonStyle(.plain)
                .disabled(isUploading)
            }
            .frame(width: 440)
            .padding(CicadaTheme.spacingXXL)
            .glassCard()
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(isDragOver ? CicadaTheme.accent : CicadaTheme.border, lineWidth: isDragOver ? 2 : 1)
                    .animation(.easeInOut(duration: 0.2), value: isDragOver)
            )
            .onDrop(of: [.fileURL], isTargeted: $isDragOver) { providers in
                handleDrop(providers: providers)
                return true
            }
            .contentShape(Rectangle())
            .onTapGesture {
                // Absorb taps so they don't propagate to background
            }
        }
    }

    private var titleText: String {
        if isUploading { return "Uploading..." }
        switch mode {
        case .conversations: return "Upload Conversations"
        case .project: return "Import into a Project"
        case .sources: return "Save Bookmarks & Links"
        }
    }

    // MARK: - M7 bank target selector

    /// Picker choosing where a project import lands: an existing bank, or a new
    /// one named in the inline field. `targetBank == nil` is the "new" sentinel.
    @ViewBuilder
    private var bankTargetSelector: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("TARGET PROJECT")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            Picker("", selection: $targetBank) {
                ForEach(banksVM.banks) { bank in
                    Text(bank.name).tag(Optional(bank.name))
                }
                Divider()
                Text("New project…").tag(Optional<String>.none)
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .frame(maxWidth: .infinity, alignment: .leading)
            .disabled(isUploading)

            if targetBank == nil {
                TextField("New project name", text: $newBankName)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .disabled(isUploading)
            }
        }
        .frame(width: 340)
    }

    /// Mascot mood for the ingestion overlay: chewing while ingesting, happy on
    /// a successful result, idle otherwise.
    private var mascotState: BookwormState {
        if isUploading { return .digesting }
        if uploadResult != nil { return .happy }
        return .awake
    }

    /// Friendly message when the sources backend hasn't shipped yet (404).
    private static func friendlyError(_ error: Error) -> String {
        if case APIError.httpError(404, _) = error {
            return "Media ingestion isn't available yet — update the Cicada backend."
        }
        return error.localizedDescription
    }

    private func saveURL() {
        let url = urlText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        isUploading = true
        errorMessage = nil
        uploadResult = nil
        Task {
            do {
                try await APIClient.shared.saveSource(url: url)
                await MainActor.run {
                    isUploading = false
                    urlText = ""
                    uploadResult = "Saved — it joins the graph after the next Sleep cycle"
                }
            } catch {
                await MainActor.run {
                    isUploading = false
                    errorMessage = Self.friendlyError(error)
                }
            }
        }
    }

    /// Feed-file UTTypes for the "Saved media" picker. `.xml` is a system type;
    /// `.rss`/`.atom` aren't, so derive them from the extension (nil-safe). These
    /// route through `/sources/upload` -> `parse_upload` -> `parse_rss`.
    private static let feedContentTypes: [UTType] = {
        var types: [UTType] = [.xml]
        for ext in ["rss", "atom"] {
            if let t = UTType(filenameExtension: ext) { types.append(t) }
        }
        return types
    }()

    private func pickFilesOrFolder() {
        let panel = NSOpenPanel()
        switch mode {
        case .conversations:
            panel.allowedContentTypes = [.json, .html]
            panel.message = "Select export files or a folder containing them"
        case .project:
            panel.allowedContentTypes = [.json, .html, .zip]
            panel.message = "Select a Claude / ChatGPT / Gemini export (.json, .html, or .zip)"
        case .sources:
            panel.allowedContentTypes = [.json, .html, .commaSeparatedText, .plainText] + Self.feedContentTypes
            panel.message = "Select bookmark exports, Takeout files, RSS/Atom feeds, or URL lists"
        }
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true

        guard panel.runModal() == .OK else { return }
        uploadURLs(panel.urls)
    }

    private func handleDrop(providers: [NSItemProvider]) {
        var urls: [URL] = []
        let group = DispatchGroup()

        for provider in providers {
            group.enter()
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url { urls.append(url) }
                group.leave()
            }
        }

        group.notify(queue: .main) {
            uploadURLs(urls)
        }
    }

    private func uploadURLs(_ urls: [URL]) {
        if mode == .project {
            importToBank(urls)
            return
        }
        let allowedExts = mode == .conversations
            ? Set(["json", "html"])
            : Set(["json", "html", "csv", "txt", "xml", "rss", "atom"])
        var filesToUpload: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let fileURL as URL in enumerator {
                        let ext = fileURL.pathExtension.lowercased()
                        if allowedExts.contains(ext) {
                            if fileURL.lastPathComponent.lowercased() == "users.json" { continue }
                            filesToUpload.append(fileURL)
                        }
                    }
                }
            } else {
                let ext = url.pathExtension.lowercased()
                if allowedExts.contains(ext) {
                    filesToUpload.append(url)
                }
            }
        }

        guard !filesToUpload.isEmpty else {
            errorMessage = mode == .conversations
                ? "No JSON or HTML files found"
                : "No bookmark, Takeout, feed (XML/RSS/Atom), or URL-list files found"
            return
        }

        isUploading = true
        errorMessage = nil
        uploadResult = nil

        let uploadMode = mode
        Task {
            var totalCreated = 0
            var totalUpdated = 0
            var totalSkipped = 0
            var firstError: String?

            for url in filesToUpload {
                do {
                    let response = uploadMode == .conversations
                        ? try await APIClient.shared.uploadFile(fileURL: url)
                        : try await APIClient.shared.uploadSource(fileURL: url)
                    totalCreated += response.episodesCreated
                    totalUpdated += response.episodesUpdated
                    totalSkipped += response.duplicatesSkipped
                    // Save to persistent history
                    UploadHistoryStore.shared.add(
                        UploadHistoryEntry(
                            filename: url.lastPathComponent,
                            provider: response.source,
                            date: Self.formattedNow(),
                            episodesCreated: response.episodesCreated,
                            duplicatesSkipped: response.duplicatesSkipped
                        )
                    )
                } catch {
                    if firstError == nil {
                        firstError = Self.friendlyError(error)
                    }
                }
            }

            await MainActor.run {
                isUploading = false
                if let err = firstError {
                    errorMessage = err
                } else {
                    uploadResult = Self.importSummary(created: totalCreated, updated: totalUpdated, skipped: totalSkipped)
                    // Auto-close after success
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        withAnimation(.spring(duration: 0.3)) {
                            isPresented = false
                        }
                    }
                }
            }
        }
    }

    // MARK: - M7 project import

    /// Stage conversation exports into a target memory bank via
    /// `POST /banks/{name}/import`. Accepts .json/.html/.zip (folders are walked
    /// for matching files). When the target is "new", the bank is created first.
    private func importToBank(_ urls: [URL]) {
        let allowedExts = Set(["json", "html", "zip"])
        var filesToUpload: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let fileURL as URL in enumerator {
                        if allowedExts.contains(fileURL.pathExtension.lowercased()) {
                            filesToUpload.append(fileURL)
                        }
                    }
                }
            } else if allowedExts.contains(url.pathExtension.lowercased()) {
                filesToUpload.append(url)
            }
        }

        guard !filesToUpload.isEmpty else {
            errorMessage = "No .json, .html, or .zip export files found"
            return
        }

        // Resolve the destination bank name. nil sentinel => create a new one.
        // `targetBank` already holds an existing bank's slug; `newBankName` is a
        // raw human-typed string that must be slugified to match the backend.
        let creatingNew = targetBank == nil
        let typedName = (targetBank ?? newBankName).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !typedName.isEmpty else {
            errorMessage = "Name the new project first"
            return
        }

        isUploading = true
        errorMessage = nil
        uploadResult = nil

        Task {
            // The slug the import must target. For an existing bank this is the
            // selection (already a slug); for a new bank it is the slug the
            // backend keyed it under, captured from create().
            let bankSlug: String
            if creatingNew {
                guard let slug = await banksVM.create(name: typedName) else {
                    await MainActor.run {
                        isUploading = false
                        errorMessage = banksVM.errorMessage ?? "Couldn't create project \"\(typedName)\""
                    }
                    return
                }
                bankSlug = slug
            } else {
                bankSlug = typedName
            }
            let bankName = bankSlug

            var totalStaged = 0
            var totalUpdated = 0
            var totalSkipped = 0
            var minDate: String?
            var maxDate: String?
            var firstError: String?

            for url in filesToUpload {
                do {
                    let resp = try await APIClient.shared.importToBank(name: bankName, fileURL: url)
                    totalStaged += resp.episodesStaged
                    totalUpdated += resp.episodesUpdated
                    totalSkipped += resp.duplicatesSkipped
                    if let from = resp.dateRange?.from {
                        if minDate == nil || from < minDate! { minDate = from }
                    }
                    if let to = resp.dateRange?.to {
                        if maxDate == nil || to > maxDate! { maxDate = to }
                    }
                } catch {
                    if firstError == nil { firstError = Self.friendlyError(error) }
                }
            }

            // Reload banks so counts/roster reflect the import.
            await banksVM.load()
            // If we imported into the active bank, refresh the graph in place.
            let isActive = banksVM.activeName == bankName
            if isActive {
                await graphVM.loadGraph()
            }

            await MainActor.run {
                isUploading = false
                if let err = firstError, totalStaged == 0 {
                    errorMessage = err
                } else {
                    var msg = "Imported into \"\(bankName)\"\n"
                    msg += Self.importSummary(created: totalStaged, updated: totalUpdated, skipped: totalSkipped)
                    if let from = minDate, let to = maxDate {
                        msg += "\n\(from) → \(to)"
                    }
                    uploadResult = msg
                    targetBank = bankName
                    newBankName = ""
                }
            }
        }
    }

    /// One-line ingestion summary, e.g. "12 new · 3 updated · 40 unchanged".
    /// G20 surfaces re-staged (grown/edited) threads as their own "updated"
    /// clause instead of hiding them inside the unchanged/skipped count; the
    /// clause is omitted when nothing was updated to avoid noise.
    private static func importSummary(created: Int, updated: Int, skipped: Int) -> String {
        var parts = ["\(created) new"]
        if updated > 0 { parts.append("\(updated) updated") }
        parts.append("\(skipped) unchanged")
        return parts.joined(separator: " · ")
    }

    private static func formattedNow() -> String {
        let f = DateFormatter()
        f.dateFormat = "MMM d, yyyy h:mm a"
        return f.string(from: Date())
    }
}

// MARK: - Shared Upload History Store

@Observable
final class UploadHistoryStore {
    static let shared = UploadHistoryStore()
    var entries: [UploadHistoryEntry] = []

    private let historyURL: URL = {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("Cicada", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("upload_history.json")
    }()

    init() {
        load()
    }

    func add(_ entry: UploadHistoryEntry) {
        entries.insert(entry, at: 0)
        save()
    }

    func remove(id: String) {
        entries.removeAll { $0.id == id }
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: historyURL),
              let loaded = try? JSONDecoder().decode([UploadHistoryEntry].self, from: data)
        else { return }
        entries = loaded
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(entries) else { return }
        try? data.write(to: historyURL)
    }
}
