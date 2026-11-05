import AppKit
import SwiftUI

// ROR-117 / G43, owner ruling 68 — an added recording, video or photo is a page in memory (`media_pages`). The page
// leads with the file itself — the player or the photo, the same seam the viewer sheet uses (`MediaPlayerPane`,
// `PhotoViewer`, `MissingFilePane`; no second player) — then one line of facts, then the article, then the recording's
// words with each timestamp a click that seeks the player. The words are read from `GET /files/{id}/transcript` when
// the page opens and live in this view's state only: they are kept outside every bank, never in the page's markdown.
//
// DR-5 (no accent: the facts and the stamps are ink tokens), DR-9 (the player area is a filled shape, no border or
// shadow), DR-59 (one label, no explanatory paragraph), DR-60 (a seek is the person's own act and never animates; the
// page never autoplays), DR-71 (tokens only), DR-78 (the article is the server's; this is the media card above it),
// DR-81 (nothing to say draws nothing: a photo or a file with no words has no words section).

/// `GET /files/{id}/transcript` — the recording's words, each with its start and end in seconds.
struct FileTranscript: Decodable, Equatable {
    struct Segment: Decodable, Equatable {
        let start: Double
        let end: Double
        let text: String
    }

    let segments: [Segment]
    let transcribedBy: String?
    let language: String?
}

/// Every rule the page makes about the file, pure — so `MediaPageModelTests` pins them.
enum MediaPageModel {
    /// "Recording · 1:05 · Mar 2": what kind it is, how long, and its own date. A photo has no length; a missing
    /// date says nothing.
    static func facts(_ block: MediaBlock, today: ISODay = .today(), locale: Locale = .autoupdatingCurrent) -> String {
        let day = ISODay(block.recordedAt).map { RelativeDay.absolute($0, today: today, locale: locale) } ?? ""
        let length = block.durationS.map { MediaViewerModel.clock(Double($0)) } ?? ""
        return Eyebrow.text(kind(block.mediaType), length, day)
    }

    static func kind(_ mediaType: String) -> String {
        switch mediaType {
        case "video": Copy.mediaKindVideo
        case "photo": Copy.mediaKindPhoto
        default: Copy.mediaKindRecording
        }
    }

    /// Who made these words (owner 2026-11-05: the model that transcribed it is named). Nil when none was recorded.
    static func transcribedLine(_ transcript: FileTranscript) -> String? {
        guard let name = transcript.transcribedBy?.trimmingCharacters(in: .whitespaces), !name.isEmpty else { return nil }
        return Copy.mediaTranscribedBy(name)
    }

    /// A timestamp seeks only when a player is there to seek: a photo, or a file that is not on this Mac, has none.
    static func canSeek(_ target: MediaViewerModel.Target) -> Bool {
        if case .play = target { return true }
        return false
    }

    /// The player's height on the page: a video wants a picture's room, a recording a bar's.
    static func playerHeight(_ target: MediaViewerModel.Target) -> CGFloat {
        switch target {
        case .play(_, let kind, _): kind == .video ? 340 : 190
        case .photo: 340
        case .missing: 150
        }
    }

    /// Whether the page draws the words at all: only when the file has some.
    static func hasWords(_ transcript: FileTranscript?) -> Bool {
        !(transcript?.segments.isEmpty ?? true)
    }

    /// ROR-117 / ruling 68: the page has words and its `## Summary` is empty, so the one quiet action is offered.
    /// A page with no such heading (the person took it out) is theirs, and a filled summary needs no action.
    static func canRead(_ transcript: FileTranscript?, markdown: String) -> Bool {
        hasWords(transcript) && summaryIsEmpty(markdown)
    }

    static func summaryIsEmpty(_ markdown: String) -> Bool {
        var inSummary = false
        var found = false
        for line in markdown.split(separator: "\n", omittingEmptySubsequences: false) {
            let text = line.trimmingCharacters(in: .whitespaces)
            if text.hasPrefix("## ") {
                if inSummary { break }
                inSummary = text.dropFirst(3).trimmingCharacters(in: .whitespaces).lowercased() == "summary"
                found = found || inSummary
            } else if inSummary, !text.isEmpty {
                return false
            }
        }
        return found
    }
}

/// What the head and the words share on one page: where the file is, and the player that plays it.
@MainActor
@Observable
final class MediaPageSession {
    var target: MediaViewerModel.Target = .missing
    var controller: VideoPlaybackController?
}

/// The head of a recording's page: the player or the photo, and one line of facts.
struct MediaPageHead: View {
    let media: MediaBlock
    let session: MediaPageSession
    var places = MediaFileIndexer.shared.places

    @State private var record: AddedFile?
    @State private var image: NSImage?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            surface
                .frame(maxWidth: .infinity)
                .frame(height: CicadaTheme.scaled(MediaPageModel.playerHeight(session.target)))
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            let facts = MediaPageModel.facts(media)
            if !facts.isEmpty {
                Text(facts).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .task(id: media.fileId) { await resolve() }
    }

    @ViewBuilder
    private var surface: some View {
        switch session.target {
        case .play(let url, let kind, let start):
            MediaPlayerPane(url: url, kind: kind, start: start, autoplay: false) { session.controller = $0 }
        case .photo:
            if let image {
                PhotoViewer(image: image)
            } else {
                CicadaTheme.bgPane
            }
        case .missing:
            MissingFilePane(id: media.fileId ?? "", record: record, places: places) { Task { await resolve() } }
        }
    }

    private func resolve() async {
        guard let id = media.fileId else { return }
        session.target = MediaViewerModel.target(id: id, at: nil, places: places)
        if case .photo(let url) = session.target { image = NSImage(contentsOf: url) } else { image = nil }
        // The name and source of a file that is gone come from the list, so the sentence can say what to do.
        record = (try? await APIClient.shared.addedFiles())?.first { $0.id == id }
    }
}

/// The recording's words, below the article: a stamp per segment that seeks the player, then what was said.
struct MediaPageTranscript: View {
    let fileId: String
    let session: MediaPageSession
    /// The page's markdown, so the one action shows only while its summary is empty.
    var markdown: String = ""
    /// The page again, after a read wrote it.
    var changed: () -> Void = {}

    @State private var transcript: FileTranscript?
    @State private var reading = false
    @State private var failed = false

    var body: some View {
        // Not a `Group`: it passes modifiers to its children, and with no words yet it has none, so the task never ran.
        VStack(alignment: .leading, spacing: 0) {
            if MediaPageModel.hasWords(transcript), let transcript {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SectionLabel(Copy.mediaWordsTitle)
                    if MediaPageModel.canRead(transcript, markdown: markdown) { readAction }
                    if let line = MediaPageModel.transcribedLine(transcript) {
                        Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(Array(transcript.segments.enumerated()), id: \.offset) { _, segment in row(segment) }
                    }
                }
            } else {
                Color.clear.frame(height: 0)
            }
        }
        .task(id: fileId) { transcript = try? await APIClient.shared.fileTranscript(id: fileId) }
    }

    private var readAction: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(reading ? Copy.mediaReading : Copy.mediaReadNow) { read() }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .disabled(reading)
            if failed {
                Text(Copy.mediaReadFailed).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func read() {
        reading = true
        failed = false
        Task {
            do {
                try await APIClient.shared.readFile(id: fileId)
                changed()
            } catch {
                failed = true
            }
            reading = false
        }
    }

    private func row(_ segment: FileTranscript.Segment) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            stamp(segment.start)
            Text(segment.text)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func stamp(_ start: Double) -> some View {
        let label = Text(MediaViewerModel.clock(start))
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .monospacedDigit()
        if MediaPageModel.canSeek(session.target), let controller = session.controller {
            Button { MediaViewerModel.begin(controller, at: start) } label: { label }
                .buttonStyle(.cicadaPlain)
                .frame(width: CicadaTheme.scaled(56), alignment: .trailing)
        } else {
            label.frame(width: CicadaTheme.scaled(56), alignment: .trailing)
        }
    }
}
