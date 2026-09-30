import AppKit
import SwiftUI

/// G162 — "What Cicada has from this video", inside a saved video's detail column (the Feed) and the entity card's
/// media block (M6). What the server says Cicada holds — a `Tag`, who recorded it (data: the harness's app, the model
/// the turn join found, the day), whether Sleep has read it and how faithful the words are, the record's first quote
/// in the plain quote face — then the queue's state and the buttons the state allows (`VideoActions`). Nothing here
/// fetches, downloads or watches a video: a Queue tap puts the person's own request in a queue outside the bank, and
/// their agent does the rest with its own tools (Track V; R-VU4).
///
/// A backend without the video routes (`VideoStateCache.isGone`) or a video the state does not name draws nothing.
struct VideoBlock: View {
    /// The Feed's own join key, `mediaEntityId|url`.
    let feedId: String
    let url: String
    let title: String
    let mediaEntityId: String
    /// Space above the block, drawn only when there is a block (an older backend or a non-video draws nothing).
    var topPadding: CGFloat = 0

    // Optional, like the evidence chips' (a host outside the main window, or a layout test, renders nothing
    // rather than trapping).
    @Environment(VideoStateCache.self) private var videoCache: VideoStateCache?
    @Environment(ProvenanceCache.self) private var provenanceCache: ProvenanceCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(Store.self) private var store: Store?
    @State private var record: EpisodeText?
    @State private var busy = false

    private var state: VideoStateItem? {
        guard let videoCache else { return nil }
        return videoCache.item(feedId: feedId) ?? videoCache.item(mediaEntityId: mediaEntityId, url: url)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let videoCache, !videoCache.isGone, let state {
                content(state)
                    .padding(.top, topPadding)
                    .task(id: state.episodeId ?? "") { await loadRecord(state.episodeId) }
            }
        }
        // A host that never read the states (the entity card on the Graph) asks once; a 304 costs nothing after.
        .task { if let videoCache, !videoCache.hasRead, !videoCache.isGone { await videoCache.refresh() } }
    }

    /// True for a page the Feed would show as a video — the entity card's gate (the Feed's own is `FeedKind.of`).
    static func isVideo(_ media: MediaBlock) -> Bool {
        media.kind != "paper"
            && (media.mediaType == "youtube" || media.mediaType == "video" || VideoRef.resolve(media.url) != nil)
    }

    @ViewBuilder
    private func content(_ state: VideoStateItem) -> some View {
        let actions = VideoActions.for(state, permission: nil)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Videos.blockTitle)
            HStack(spacing: CicadaTheme.spacingSM) {
                if let tag = VideoWords.stateTag(state.state) { Tag(text: tag) }
                if state.state != .none, let line = attribution(state) {
                    if let harness = state.recordedBy { OriginMark(origin: harness, size: CicadaTheme.scaled(12)) }
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            if state.state == .recorded { tertiary(Copy.Videos.legacyRecord) }
            statusLine(actions.status)
            if state.state == .none { tertiary(Copy.Videos.onlyMetadata) }
            if let sleep = VideoWords.sleepLine(state) { bodyLine(sleep) }
            if let quote = record.flatMap(VideoQuote.first) { quoteView(quote) }
            if state.state != .recorded, let caveat = VideoWords.caveatLine(state) { tertiary(caveat) }
            if actions.showsBrowserLine { tertiary(Copy.Videos.browserPermissionOff) }
            buttons(state, actions)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func attribution(_ state: VideoStateItem) -> String? {
        VideoWords.attribution(recordedBy: state.recordedBy, recordedAt: state.recordedAt,
                               model: record?.watch?.authorModel, effort: record?.watch?.authorEffort)
    }

    private func bodyLine(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func tertiary(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder
    private func statusLine(_ status: VideoActionSet.Status) -> some View {
        switch status {
        case .none:
            EmptyView()
        case .queued(let want):
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.Videos.inQueue(want)).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                removeLink
            }
        case .pickedUp(let by, let want):
            HStack(spacing: CicadaTheme.spacingXS) {
                if let by { OriginMark(origin: by, size: CicadaTheme.scaled(12)) }
                Text(Copy.Videos.pickedUpBy(VideoWords.agentName(by), want: want))
                    .font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                removeLink
            }
        case .failed(_, let reason):
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
                Text(Copy.Videos.couldntDo(reason))
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var removeLink: some View {
        TextButton(title: Copy.Videos.remove, help: Copy.Videos.removeHelp, inline: true) { run { await videoCache?.remove(key: $0) } }
    }

    private func quoteView(_ quote: (text: String, time: String?)) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            RoundedRectangle(cornerRadius: 1).fill(CicadaTheme.textTertiary).frame(width: 2)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(quote.text)
                    .font(CicadaTheme.quoteFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Text(Copy.Videos.fromTheVideo(quote.time))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func buttons(_ state: VideoStateItem, _ actions: VideoActionSet) -> some View {
        let hasRecord = state.episodeId != nil && state.state != .none
        if actions.queueTranscript.isShown || actions.queueWatch.isShown || actions.showsTryAgain || hasRecord {
            HStack(spacing: CicadaTheme.spacingSM) {
                availability(actions.queueTranscript, title: Copy.Videos.queueTranscript) { key in
                    await videoCache?.queue(key: key, want: .transcript)
                }
                availability(actions.queueWatch, title: Copy.Videos.queueWatch) { key in
                    await videoCache?.queue(key: key, want: .watch)
                }
                if actions.showsTryAgain {
                    NeutralButton(title: Copy.Videos.tryAgain, size: .compact, isDisabled: busy) {
                        run { await videoCache?.retry(key: $0) }
                    }
                    NeutralButton(title: Copy.Videos.remove, size: .compact, isDisabled: busy, help: Copy.Videos.removeHelp) {
                        run { await videoCache?.remove(key: $0) }
                    }
                }
                if actions.showsOpenInBrowser, let link = URL(string: url),
                   ["http", "https"].contains(link.scheme?.lowercased() ?? "") {
                    TextButton(title: Copy.Videos.openInBrowser, help: Copy.Videos.openInBrowserHelp) {
                        NSWorkspace.shared.open(link)
                    }
                }
                if hasRecord, let episode = state.episodeId, let provenance {
                    // DR-5 use 5 — a link.
                    Button(Copy.Videos.openRecord) {
                        provenance.open(ReaderTarget(episode: episode, subjectId: mediaEntityId, knownTitle: title,
                                                     knownHarness: state.recordedBy))
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.accentText)
                    .help(Copy.Videos.openRecordHelp)
                    .padding(.leading, CicadaTheme.spacingSM)
                }
            }
            .padding(.top, CicadaTheme.spacingXS)
        }
    }

    @ViewBuilder
    private func availability(_ availability: VideoAvailability, title: String,
                              perform: @escaping (String) async -> String?) -> some View {
        switch availability {
        case .hidden:
            EmptyView()
        case .enabled(let help):
            NeutralButton(title: title, size: .compact, isDisabled: busy, help: help ?? title) { run(perform) }
        case .disabled(let help):
            NeutralButton(title: title, size: .compact, isDisabled: true, help: help, disabledHelp: help) {}
        }
    }

    /// One write at a time; a failure shows the server's own sentence (a 422) or a plain line.
    private func run(_ perform: @escaping (String) async -> String?) {
        guard !busy, let key = state?.key else { return }
        busy = true
        Task {
            if let sentence = await perform(key) { store?.toast = sentence }
            busy = false
        }
    }

    private func loadRecord(_ episode: String?) async {
        guard let episode, let provenanceCache else { record = nil; return }
        record = await provenanceCache.document(episode: episode, focus: .none).value
    }
}
