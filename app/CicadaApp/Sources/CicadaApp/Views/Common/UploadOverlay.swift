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
    case sources = "Saved media"
}

struct UploadOverlay: View {
    @Binding var isPresented: Bool
    @State private var isDragOver = false
    @State private var isUploading = false
    @State private var uploadResult: String?
    @State private var errorMessage: String?
    @State private var mode: UploadMode = .conversations
    @State private var urlText = ""

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
                .onChange(of: mode) { _, _ in
                    uploadResult = nil
                    errorMessage = nil
                }

                Image(systemName: iconName)
                    .font(.system(size: 44))
                    .foregroundStyle(isDragOver ? CicadaTheme.accent : CicadaTheme.textTertiary)
                    .symbolEffect(.pulse, isActive: isUploading)

                Text(isUploading ? "Uploading..." : (mode == .conversations ? "Upload Conversations" : "Save Bookmarks & Links"))
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
                } else {
                    Text("Drop a browser bookmarks export (HTML/JSON),\na Takeout watch-later file, or paste a URL below")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .multilineTextAlignment(.center)
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

    private var iconName: String {
        if isUploading { return "arrow.up.circle" }
        return mode == .conversations ? "arrow.up.doc.fill" : "bookmark.fill"
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

    private func pickFilesOrFolder() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = mode == .conversations
            ? [.json, .html]
            : [.json, .html, .commaSeparatedText, .plainText]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = mode == .conversations
            ? "Select export files or a folder containing them"
            : "Select bookmark exports, Takeout files, or URL lists"

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
        let allowedExts = mode == .conversations
            ? Set(["json", "html"])
            : Set(["json", "html", "csv", "txt"])
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
                : "No bookmark, Takeout, or URL-list files found"
            return
        }

        isUploading = true
        errorMessage = nil
        uploadResult = nil

        let uploadMode = mode
        Task {
            var totalCreated = 0
            var totalSkipped = 0
            var firstError: String?

            for url in filesToUpload {
                do {
                    let response = uploadMode == .conversations
                        ? try await APIClient.shared.uploadFile(fileURL: url)
                        : try await APIClient.shared.uploadSource(fileURL: url)
                    totalCreated += response.episodesCreated
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
                    uploadResult = "Imported \(totalCreated) episodes" + (totalSkipped > 0 ? " (\(totalSkipped) duplicates)" : "")
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
