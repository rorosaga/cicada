import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The LinkedIn tile's second way in (2026-10-16, G154's pattern): the person's `Connections.csv` — or the export
/// `.zip` carrying it — enriches the people Cicada already has. The app reads the file the person picked or dropped and
/// posts its bytes; the backend matches, previews and writes. Counts only on screen, never a name.
struct LinkedInConnectionsPanel: View {
    enum Stage: Equatable {
        case idle
        case reading(String)
        case preview(LinkedInConnectionsPreview, URL, String?)
        case importing
        case done(String)
        case failed(String)
    }

    @Environment(Store.self) private var store
    @State private var stage: Stage = .idle
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Connections")
                .font(CicadaTheme.font(size: 12, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(LinkedInConnectionsWords.what)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(LinkedInConnectionsWords.where_)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            stageView
        }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            guard let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url { Task { @MainActor in preview(url) } }
            }
            return true
        }
        .onDisappear { task?.cancel() }
    }

    @ViewBuilder
    private var stageView: some View {
        switch stage {
        case .idle:
            Button(LinkedInConnectionsWords.pick) { pick() }
                .accessibilityLabel("Choose your LinkedIn Connections file")
        case .reading(let name):
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Reading \(name)…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        case .preview(let preview, let url, let day):
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(LinkedInConnectionsWords.preview(preview))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: CicadaTheme.spacingSM) {
                    Button(LinkedInConnectionsWords.confirm(preview)) { confirm(url, day) }
                        .buttonStyle(.borderedProminent)
                    Button("Cancel") { stage = .idle }
                }
            }
        case .importing:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Adding…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        case .done(let words):
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                Button("Choose another file…") { pick() }
            }
        case .failed(let words):
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Button(LinkedInConnectionsWords.pick) { pick() }
            }
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.commaSeparatedText, .zip]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select Connections.csv, or LinkedIn's export .zip"
        guard panel.runModal() == .OK, let url = panel.urls.first else { return }
        preview(url)
    }

    private func preview(_ url: URL) {
        if let refusal = IntakeRouter.refusedRoot(of: [url]) {
            stage = .failed(refusal.panelText)
            return
        }
        let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
        let day = LinkedInConnectionsWords.exportedOn(fileURL: url, modified: modified)
        stage = .reading(url.lastPathComponent)
        task?.cancel()
        task = Task {
            do {
                let preview = try await APIClient.shared.previewLinkedInConnections(fileURL: url, exportedOn: day)
                guard !Task.isCancelled else { return }
                stage = .preview(preview, url, day)
            } catch {
                guard !Task.isCancelled else { return }
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    private func confirm(_ url: URL, _ day: String?) {
        stage = .importing
        task?.cancel()
        task = Task {
            do {
                let result = try await APIClient.shared.importLinkedInConnections(fileURL: url, exportedOn: day)
                await store.refresh([.graph])
                guard !Task.isCancelled else { return }
                stage = .done(LinkedInConnectionsWords.done(result))
            } catch {
                guard !Task.isCancelled else { return }
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }
}
