import SwiftUI
import AppKit
import UniformTypeIdentifiers
import Foundation

/// The Capture / Sources page: manual one-off import (chat exports, bookmark
/// files, RSS feeds, pasted links), a summary of the keyless synced-apps
/// pipeline (Chrome/Safari bookmark sync), and an honest read on how much is
/// sitting in the Sleep queue right now. Everything lands in the same
/// `episodes/` inbox the MCP-native capture path uses — this page is the
/// manual front door onto that same pipeline, not a separate one.
struct SourcesView: View {
    @Environment(SleepViewModel.self) private var sleepVM

    // Import section
    @State private var isImporting = false
    @State private var importResult: String?
    @State private var importError: String?
    @State private var activeInline: InlineImport?
    @State private var inlineText = ""

    // Synced apps section
    @State private var isSyncing = false
    @State private var syncResult: String?
    @State private var syncError: String?
    @State private var showSyncSetup = false

    // Queue section
    @State private var status: StatusSnapshot?
    @State private var statusLoading = false
    @State private var statusError: String?

    private enum InlineImport {
        case rss, pasteURL
    }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: "Capture",
                subtitle: "Import sources manually, or connect apps that sync automatically."
            )

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    importCard
                    syncedAppsCard
                    queueCard
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .task { await loadStatus() }
        .onChange(of: sleepVM.isRunning) { _, running in
            // A cycle kicked off from the Consolidate button (or anywhere else
            // in the app) just finished — the queue count this page shows is
            // now stale, so refresh it.
            if !running { Task { await loadStatus() } }
        }
        .sheet(isPresented: $showSyncSetup) {
            SyncSetupView(onDone: { showSyncSetup = false })
        }
    }

    // MARK: - Import

    private var importCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("IMPORT")
            Text("One-off ingestion — pick a file or paste a link. Everything lands in the queue below for the next Sleep cycle.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: CicadaTheme.spacingMD) {
                ImportTileButton(
                    icon: "bubble.left.and.bubble.right",
                    label: "Chat export",
                    isBusy: isImporting
                ) { pickChatExport() }

                ImportTileButton(
                    icon: "bookmark",
                    label: "Bookmarks file",
                    isBusy: isImporting
                ) { pickBookmarksFile() }

                ImportTileButton(
                    icon: "dot.radiowaves.up.forward",
                    label: "RSS feed",
                    isBusy: isImporting,
                    isActive: activeInline == .rss
                ) { toggleInline(.rss) }

                ImportTileButton(
                    icon: "link",
                    label: "Paste URL",
                    isBusy: isImporting,
                    isActive: activeInline == .pasteURL
                ) { toggleInline(.pasteURL) }
            }

            if activeInline != nil {
                inlineInputRow
            }

            if isImporting {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Importing…")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if let result = importResult {
                Text(result)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(Color(hex: 0x22C55E))
            } else if let err = importError {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(err)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(Color(hex: 0xEF4444))
                    Button("Retry") { retryLastInline() }
                        .buttonStyle(.plain)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.accent)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    @ViewBuilder
    private var inlineInputRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: activeInline == .rss ? "dot.radiowaves.up.forward" : "link")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textTertiary)
            TextField(
                activeInline == .rss ? "https://example.com/feed.xml" : "https://…",
                text: $inlineText
            )
            .textFieldStyle(.plain)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .onSubmit { submitInline() }

            Button(activeInline == .rss ? "Add feed" : "Save") { submitInline() }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(inlineText.trimmingCharacters(in: .whitespaces).isEmpty ? CicadaTheme.textTertiary : CicadaTheme.accent)
                .disabled(inlineText.trimmingCharacters(in: .whitespaces).isEmpty || isImporting)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.surfaceHover)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func toggleInline(_ which: InlineImport) {
        importError = nil
        importResult = nil
        if activeInline == which {
            activeInline = nil
        } else {
            activeInline = which
            inlineText = ""
        }
    }

    private func submitInline() {
        let text = inlineText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let which = activeInline else { return }

        isImporting = true
        importError = nil
        importResult = nil

        Task {
            do {
                switch which {
                case .rss:
                    let r = try await APIClient.shared.ingestRSS(feedUrl: text)
                    await MainActor.run { importResult = importSummary(created: r.episodesCreated, skipped: r.duplicatesSkipped) }
                case .pasteURL:
                    let r = try await APIClient.shared.saveURL(text)
                    await MainActor.run { importResult = r.message }
                }
                await MainActor.run {
                    isImporting = false
                    inlineText = ""
                    activeInline = nil
                }
                await loadStatus()
            } catch {
                await MainActor.run {
                    isImporting = false
                    importError = Self.friendlyError(error)
                }
            }
        }
    }

    /// "Retry" on an inline-import error just re-submits whatever's still in
    /// the field; a picker failure has no state worth retrying automatically
    /// (the user re-opens the tile instead).
    private func retryLastInline() {
        guard activeInline != nil, !inlineText.isEmpty else { return }
        submitInline()
    }

    private func pickChatExport() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = "Select a Claude, ChatGPT, or Gemini conversation export"
        guard panel.runModal() == .OK else { return }
        let files = expandToFiles(panel.urls, exts: ["json", "html"])
        guard !files.isEmpty else {
            importError = "No JSON or HTML files found"
            importResult = nil
            return
        }
        runImport(files: files) { url in try await APIClient.shared.uploadFile(fileURL: url) }
    }

    private func pickBookmarksFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "Select a browser bookmarks export (HTML or JSON)"
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        runImport(files: panel.urls) { url in try await APIClient.shared.uploadSource(fileURL: url) }
    }

    private func expandToFiles(_ urls: [URL], exts: Set<String>) -> [URL] {
        var result: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let fileURL as URL in enumerator {
                        if exts.contains(fileURL.pathExtension.lowercased()) {
                            result.append(fileURL)
                        }
                    }
                }
            } else if exts.contains(url.pathExtension.lowercased()) {
                result.append(url)
            }
        }
        return result
    }

    private func runImport(files: [URL], upload: @escaping (URL) async throws -> UploadResponse) {
        isImporting = true
        importError = nil
        importResult = nil

        Task {
            var created = 0
            var skipped = 0
            var firstError: String?

            for file in files {
                do {
                    let r = try await upload(file)
                    created += r.episodesCreated
                    skipped += r.duplicatesSkipped
                } catch {
                    if firstError == nil { firstError = Self.friendlyError(error) }
                }
            }

            await MainActor.run {
                isImporting = false
                if created == 0, let err = firstError {
                    importError = err
                } else {
                    var summary = importSummary(created: created, skipped: skipped)
                    if firstError != nil { summary += " (some files failed)" }
                    importResult = summary
                }
            }
            await loadStatus()
        }
    }

    private func importSummary(created: Int, skipped: Int) -> String {
        "Imported \(created), skipped \(skipped)"
    }

    // MARK: - Synced apps

    private var syncedAppsCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("SYNCED APPS")

            HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text("Chrome and Safari bookmarks sync straight from your local bookmark files — no login, no OAuth.")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)

                    if isSyncing {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            ProgressView().controlSize(.small)
                            Text("Syncing…")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    } else if let result = syncResult {
                        Text(result)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(Color(hex: 0x22C55E))
                    } else if let err = syncError {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Text(err)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(Color(hex: 0xEF4444))
                            Button("Retry") { Task { await syncBookmarksNow() } }
                                .buttonStyle(.plain)
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(CicadaTheme.accent)
                        }
                    }
                }

                Spacer(minLength: CicadaTheme.spacingMD)

                VStack(alignment: .trailing, spacing: CicadaTheme.spacingSM) {
                    Button {
                        showSyncSetup = true
                    } label: {
                        HStack(spacing: 4) {
                            Text("Set up synced apps")
                            Image(systemName: "arrow.right")
                        }
                        .font(.system(size: 13, weight: .semibold))
                        .padding(.horizontal, CicadaTheme.spacingLG)
                        .padding(.vertical, CicadaTheme.spacingSM)
                        .background(CicadaTheme.accent.opacity(0.9))
                        .foregroundStyle(.white)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)

                    Button {
                        Task { await syncBookmarksNow() }
                    } label: {
                        Text("Sync bookmarks now")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .disabled(isSyncing)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func syncBookmarksNow() async {
        isSyncing = true
        syncError = nil
        syncResult = nil
        do {
            let r = try await APIClient.shared.syncBookmarks()
            await MainActor.run {
                isSyncing = false
                syncResult = "\(r.new) new · \(r.skipped) skipped"
            }
            await loadStatus()
        } catch {
            await MainActor.run {
                isSyncing = false
                syncError = Self.friendlyError(error)
            }
        }
    }

    // MARK: - Queue

    private var queueCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("QUEUE")

            if statusLoading && status == nil {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking the queue…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if let err = statusError, status == nil {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundStyle(Color(hex: 0xEF4444))
                    Text(err)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Button("Retry") { Task { await loadStatus() } }
                        .buttonStyle(.plain)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.accent)
                }
            } else {
                let count = status?.episodes.unprocessed ?? 0
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    Image(systemName: count == 0 ? "checkmark.circle" : "tray.full")
                        .font(.system(size: 18))
                        .foregroundStyle(count == 0 ? Color(hex: 0x22C55E) : CicadaTheme.accent)
                        .frame(width: 44, height: 44)
                        .background(RoundedRectangle(cornerRadius: 10).fill(CicadaTheme.surfaceElevated))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(count == 0 ? "All caught up" : "\(count) item\(count == 1 ? "" : "s") queued for the next Sleep cycle")
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if count > 0 {
                            Text("Consolidate now to fold them into the graph immediately.")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        } else if let last = formattedLastSleep {
                            Text("Last consolidated \(last)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }

                    Spacer()

                    consolidateButton(count: count)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func consolidateButton(count: Int) -> some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await loadStatus()
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(.system(size: 12))
                }
                Text(sleepVM.isRunning ? "Sleeping…" : "Consolidate now")
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(count == 0 && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(count == 0 && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(sleepVM.isRunning || count == 0)
        .help(count == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
    }

    /// A short relative/absolute rendering of `status.lastSleepAt` for the
    /// "all caught up" state — `StatusSnapshot.parseDate` already tolerates
    /// both fractional- and plain-second ISO8601 variants the backend emits.
    private var formattedLastSleep: String? {
        guard let date = StatusSnapshot.parseDate(status?.lastSleepAt) else { return nil }
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return f.string(from: date)
    }

    private func loadStatus() async {
        statusLoading = true
        do {
            let s = try await APIClient.shared.fetchStatus()
            await MainActor.run {
                status = s
                statusError = nil
                statusLoading = false
            }
        } catch {
            await MainActor.run {
                statusError = Self.friendlyError(error)
                statusLoading = false
            }
        }
    }

    // MARK: - Shared

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .foregroundStyle(CicadaTheme.textTertiary)
            .tracking(1.2)
    }

    /// Surfaces the backend's `{"detail": "..."}` body when present instead of
    /// dumping raw JSON, and gives 404 a friendly "not shipped yet" spin —
    /// mirrors `UploadOverlay.friendlyError`.
    private static func friendlyError(_ error: Error) -> String {
        if case APIError.httpError(let code, let msg) = error {
            if code == 404 { return "That endpoint isn't available yet — update the Cicada backend." }
            if let data = msg.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = obj["detail"] as? String {
                return detail
            }
            return msg
        }
        return error.localizedDescription
    }
}

// MARK: - Import tile button

private struct ImportTileButton: View {
    let icon: String
    let label: String
    var isBusy: Bool = false
    var isActive: Bool = false
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(isActive ? CicadaTheme.accent : CicadaTheme.textSecondary)
                Text(label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(isActive ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CicadaTheme.spacingLG)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isActive ? CicadaTheme.accent.opacity(0.12) : (isHovered ? CicadaTheme.surfaceHover : CicadaTheme.surfaceElevated))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(isActive ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(isBusy)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}
