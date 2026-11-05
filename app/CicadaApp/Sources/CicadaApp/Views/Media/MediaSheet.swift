import AppKit
import SwiftUI

// ROR-117 / G43 — recordings, videos and photos open inside the app. One sheet (DR-33's grammar for a panel that is not
// a page: a title, an ✕, Esc closes, DR-60), two faces: the list of what was added, and one file. The player is the
// existing seam (`VideoPlaybackController`, R-V6 — no AVFoundation import here); a photo is the existing
// `ImageLightbox`. DR-5: no accent. DR-9: rings, not borders. DR-59: a sentence at most, no title repeating its body.

struct MediaSheet: View {
    @State var route: MediaRoute
    /// Opened from the list: a ‹ goes back to it. Opened by a hit: just the file.
    @State private var cameFromList = false
    /// The File → Add door, for the list's empty state.
    var onAdd: () -> Void = {}
    var places = MediaFileIndexer.shared.places
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            switch route {
            case .list:
                MediaSheetHeader(title: Copy.mediaFilesTitle, close: close)
                AddedFilesList(onAdd: onAdd) { file in
                    cameFromList = true
                    route = .file(id: file.id, at: nil)
                }
            case .file(let id, let at):
                MediaFilePane(id: id, at: at, places: places, back: cameFromList ? { route = .list } : nil, close: close)
                    .id(id)
            }
        }
        .frame(width: CicadaTheme.scaled(880), height: CicadaTheme.scaled(600))
        .background(CicadaTheme.bgBase)
        .onExitCommand { close() }
    }
}

/// The sheet's one header: ‹ (when there is a list to go back to), the name, Open in default app, ✕.
struct MediaSheetHeader: View {
    let title: String
    var back: (() -> Void)?
    var openDefault: (() -> Void)?
    let close: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let back {
                IconButton(systemName: "chevron.left", help: Copy.mediaBack, action: back)
            }
            Text(title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .truncationMode(.middle)
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let openDefault {
                IconButton(systemName: "arrow.up.right.square", help: Copy.mediaOpenDefault, action: openDefault)
            }
            IconButton(systemName: "xmark", help: Copy.mediaClose, action: close)
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}

// MARK: - One file

/// A file: resolved by `MediaViewerModel`, then a player, a viewer or one sentence.
private struct MediaFilePane: View {
    let id: String
    let at: Double?
    let places: MediaFilePlaces
    var back: (() -> Void)?
    let close: () -> Void

    @State private var target: MediaViewerModel.Target = .missing
    @State private var record: AddedFile?

    var body: some View {
        VStack(spacing: 0) {
            MediaSheetHeader(title: title, back: back, openDefault: playableURL.map { url in { NSWorkspace.shared.open(url) } },
                             close: close)
            content
        }
        .task(id: id) {
            target = MediaViewerModel.target(id: id, at: at, places: places)
            // The name and kind of a file that is gone come from the list, so the sentence can say what to do.
            record = (try? await APIClient.shared.addedFiles())?.first { $0.id == id }
        }
    }

    private var playableURL: URL? {
        switch target {
        case .play(let url, _, _), .photo(let url): url
        case .missing: nil
        }
    }

    private var title: String {
        playableURL?.lastPathComponent ?? record?.name ?? ""
    }

    @ViewBuilder
    private var content: some View {
        switch target {
        case .play(let url, let kind, let start):
            MediaPlayerPane(url: url, kind: kind, start: start)
        case .photo(let url):
            if let image = NSImage(contentsOf: url) {
                PhotoViewer(image: image)
            } else {
                MissingFilePane(id: id, record: record, places: places) { target = MediaViewerModel.target(id: id, at: at, places: places) }
            }
        case .missing:
            MissingFilePane(id: id, record: record, places: places) { target = MediaViewerModel.target(id: id, at: at, places: places) }
        }
    }
}

/// R-V6 — the player itself, held as the protocol. Starts at the hit's second and plays; closing the surface stops
/// it and lets go of the file (the sheet's `onDisappear`), so nothing keeps running.
private struct MediaPlayerPane: View {
    let url: URL
    let kind: MediaKind
    let start: Double

    @State private var controller: VideoPlaybackController?

    var body: some View {
        Group {
            if let controller {
                if kind == .video {
                    AVPlayerSurface(controller: controller)
                } else {
                    AudioSurface(controller: controller)
                }
            } else {
                CicadaTheme.bgPane
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: url) {
            let c = VideoPlayerModel.controller(for: url, existing: controller, make: AVPlaybackController.init)
            controller = c
            MediaViewerModel.begin(c, at: start)
        }
        .onDisappear {
            MediaViewerModel.end(controller)
            controller = nil
        }
        .focusable()
        .onKeyPress(.space) { VideoPlayerModel.handleSpace(controller) ? .handled : .ignored }
    }
}

/// An audio file's surface: the time, a scrubber, play and pause — not an empty video box.
struct AudioSurface: View {
    let controller: VideoPlaybackController

    @State private var time: Double = 0
    @State private var length: Double?
    @State private var playing = false
    @State private var scrubbing = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            Spacer(minLength: 0)
            Image(systemName: "waveform")
                .font(CicadaTheme.font(size: 56))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(MediaViewerModel.clock(time))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .monospacedDigit()
                    .frame(width: CicadaTheme.scaled(56), alignment: .trailing)
                Slider(value: $time, in: 0...max(length ?? 1, 1)) { editing in
                    scrubbing = editing
                    if !editing { controller.seek(to: time) }
                }
                .tint(CicadaTheme.textSecondary)
                .disabled(length == nil)
                .accessibilityLabel(Copy.mediaPosition)
                Text(length.map(MediaViewerModel.clock) ?? "")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .monospacedDigit()
                    .frame(width: CicadaTheme.scaled(56), alignment: .leading)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            IconButton(systemName: playing ? "pause.fill" : "play.fill", help: playing ? Copy.mediaPause : Copy.mediaPlay) {
                controller.toggle()
                playing = controller.isPlaying
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.bgPane)
        .task {
            // The player's own clock, read four times a second; a scrub in hand is never fought.
            while !Task.isCancelled {
                if !scrubbing { time = controller.currentTime }
                length = controller.length
                playing = controller.isPlaying
                try? await Task.sleep(for: .milliseconds(250))
            }
        }
    }
}

/// R9 — a file that moved, was deleted, or is known from another device: one sentence and a way to act.
private struct MissingFilePane: View {
    let id: String
    let record: AddedFile?
    let places: MediaFilePlaces
    let found: () -> Void

    @State private var refused = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Spacer(minLength: 0)
            Text(refused ? Copy.mediaNotTheFile : Copy.mediaGone)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            // A store's own item (a memo) cannot be re-pointed by hand; a file the person added can.
            if record?.source == nil {
                NeutralButton(title: Copy.mediaChooseIt, size: .compact, action: choose)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.bgPane)
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = record?.name
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if MediaViewerModel.isTheFile(url, id: id, source: record?.source) {
            places.remember(id, url)
            refused = false
            found()
        } else {
            refused = true
        }
    }
}

// MARK: - The list

/// What was added, newest first (`GET /files`). A row opens the same player or viewer a hit does; the context menu
/// keeps Open in default app and Show in Finder (the secondary actions).
struct AddedFilesList: View {
    var onAdd: () -> Void
    var places = MediaFileIndexer.shared.places
    let open: (AddedFile) -> Void

    @State private var files: [AddedFile]?
    @State private var hovered: String?

    var body: some View {
        Group {
            if let files {
                if files.isEmpty {
                    VStack(spacing: CicadaTheme.spacingMD) {
                        Spacer(minLength: 0)
                        Text(Copy.mediaListEmpty).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        NeutralButton(title: Copy.mediaAdd, size: .compact, action: onAdd)
                        Spacer(minLength: 0)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 0) { ForEach(files) { row($0) } }
                            .padding(.horizontal, CicadaTheme.spacingMD)
                    }
                }
            } else {
                Color.clear
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task { files = (try? await APIClient.shared.addedFiles()) ?? [] }
    }

    private func row(_ file: AddedFile) -> some View {
        Button { open(file) } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                Image(systemName: file.glyph)
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(22))
                Text(file.name)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let detail = file.detail {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).monospacedDigit()
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.spacingSM)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovered = $0 ? file.id : (hovered == file.id ? nil : hovered) }
        .rowHoverFill(hovering: hovered == file.id)
        .contextMenu {
            if let url = places.url(of: file.id) {
                Button(Copy.mediaOpenDefault) { NSWorkspace.shared.open(url) }
                Button(Copy.mediaShowInFinder) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
            }
        }
    }
}
