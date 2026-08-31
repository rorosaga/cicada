import SwiftUI

/// Where an import is, from drop to summary (G71 §4.3).
enum ImportStage: Equatable {
    case idle
    /// Parsing the dropped file server-side. Nothing has been staged.
    case parsing(String)
    /// The parse came back: this is what the file contains, and the file to
    /// re-post if the user confirms.
    case preview(UploadPreview, URL)
    case importing
    case done(String)
    case failed(String)
}

/// Pure decisions the overlay makes, hoisted out of the view so they are
/// testable without SwiftUI.
enum ImportOverlayState {

    /// Plural of a collection kind. "saved" and "list" would otherwise become
    /// "saveds"; every other kind pluralises by adding an s.
    static func pluralKind(_ kind: String) -> String {
        switch kind {
        case "saved": return "saved sets"
        default: return kind + "s"
        }
    }

    /// "214 items across 6 collections" / "1 item in 1 saved".
    static func totalLine(_ preview: UploadPreview) -> String {
        let itemWord = preview.total == 1 ? "item" : "items"
        let kind = preview.collections.first?.kind ?? "collection"
        if preview.collections.count == 1 {
            return "\(preview.total) \(itemWord) in 1 \(kind)"
        }
        return "\(preview.total) \(itemWord) across \(preview.collections.count) \(pluralKind(kind))"
    }

    /// "182 new · 32 already saved" — the dedup counts the spec asks for.
    static func summary(_ response: UploadResponse) -> String {
        let newPart = response.episodesCreated == 0
            ? "Nothing new"
            : "\(response.episodesCreated) new"
        return "\(newPart) · \(response.duplicatesSkipped) already saved"
    }

    /// A preview only earns a Confirm button if it actually found something;
    /// otherwise the overlay says why, in the backend's own words.
    static func afterPreview(_ preview: UploadPreview, file: URL) -> ImportStage {
        guard preview.recognized, preview.total > 0 else {
            return .failed(preview.warnings.first
                ?? "Cicada could not read this file as a saved-content export.")
        }
        return .preview(preview, file)
    }
}

/// The live collection list plus its confirm/cancel controls.
struct ImportPreviewSection: View {
    let stage: ImportStage
    let onConfirm: (URL) -> Void
    let onCancel: () -> Void

    var body: some View {
        switch stage {
        case .idle:
            EmptyView()
        case .parsing(let filename):
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Reading \(filename)…")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .preview(let preview, let file):
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(ImportOverlayState.totalLine(preview))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(preview.collections) { collection in
                            HStack {
                                Text(collection.name)
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                Spacer()
                                Text("\(collection.count)")
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(collection.name), \(collection.count) items")
                        }
                    }
                }
                .frame(maxHeight: 140)
                ForEach(preview.warnings, id: \.self) { warning in
                    Text(warning)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.warning)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    Button("Import these") { onConfirm(file) }
                        .buttonStyle(.borderedProminent)
                        .accessibilityLabel("Import \(preview.total) items")
                    Button("Cancel", action: onCancel).buttonStyle(.bordered)
                }
            }
        case .importing:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Importing…").font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .done(let summary):
            VStack(alignment: .leading, spacing: 2) {
                Text(summary)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .failed(let message):
            Text(message)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.danger)
        }
    }
}
