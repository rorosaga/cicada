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

struct UploadOverlay: View {
    @Binding var isPresented: Bool
    @State private var isDragOver = false
    @State private var isUploading = false
    @State private var uploadResult: String?
    @State private var errorMessage: String?

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
                Image(systemName: isUploading ? "arrow.up.circle" : "arrow.up.doc.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(isDragOver ? CicadaTheme.accent : CicadaTheme.textTertiary)
                    .symbolEffect(.pulse, isActive: isUploading)

                Text(isUploading ? "Uploading..." : "Upload Conversations")
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
                } else {
                    Text("Drag and drop the folder here\nor click to select")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .multilineTextAlignment(.center)
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

    private func pickFilesOrFolder() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = "Select export files or a folder containing them"

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
        var filesToUpload: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let fileURL as URL in enumerator {
                        let ext = fileURL.pathExtension.lowercased()
                        if ext == "json" || ext == "html" {
                            if fileURL.lastPathComponent.lowercased() == "users.json" { continue }
                            filesToUpload.append(fileURL)
                        }
                    }
                }
            } else {
                let ext = url.pathExtension.lowercased()
                if ext == "json" || ext == "html" {
                    filesToUpload.append(url)
                }
            }
        }

        guard !filesToUpload.isEmpty else {
            errorMessage = "No JSON or HTML files found"
            return
        }

        isUploading = true
        errorMessage = nil
        uploadResult = nil

        Task {
            var totalCreated = 0
            var totalSkipped = 0
            var firstError: String?

            for url in filesToUpload {
                do {
                    let response = try await APIClient.shared.uploadFile(fileURL: url)
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
                        firstError = error.localizedDescription
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
