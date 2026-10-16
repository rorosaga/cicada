import SwiftUI

/// G162 — the watch run's detail column (the approved boards VideoRunEmpty, VideoPicker, VideoRunProgress and
/// VideoRunLarge). Choosing: what to ask for on each picked video, the size in words and known minutes, how the agent
/// should read, and the prompt shown BEFORE it is copied; *Copy for an agent* is the one write (every pick into the
/// queue, one batch, no cap). Progress: "2 of 5 recorded" — the numerator only moves when a record lands, never on
/// "picked up" — one segment per video up to ten, a continuous bar above, the rows flat up to ten and grouped above.
///
/// Nothing here fetches, downloads or watches a video: the person's own agent does, with its own tools (Track V's
/// rail, R-VU4); the card says so in `WatchLeavesMacNote`'s words, and names no provider (R-VU11).
struct VideoRunCard: View {
    let model: VideoRunModel
    let rows: [VideoRow]
    let padding: CGFloat
    let onLeave: () -> Void

    @Environment(VideoStateCache.self) private var cache
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(Store.self) private var store
    @State private var agentGotOpen = false
    @State private var agentGot: String?

    private var summary: VideoSummary? { cache.summary }

    /// The run under way, when there is one to show.
    private var runningBatch: VideoBatch? {
        guard model.mode == .progress, let batch = summary?.batch, batch.total > 0 else { return nil }
        return batch
    }

    /// The body scrolls inside the card and the footer stays pinned under it (VideoRunLarge; DESIGN_RULES §9
    /// 2026-09-30): a short card hugs its content, a long one — "Select all", a run above ten — scrolls its rows and
    /// keeps *Copy for an agent* / *Copy the prompt again* in view.
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ViewThatFits(in: .vertical) {
                scrollingBody
                ScrollView { scrollingBody }.scrollIndicators(.automatic)
            }
            pinnedFooter
        }
        .padding(padding)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .onChange(of: model.selected) { _, _ in model.refreshPreview(rows: rows, cache: cache) }
        .onChange(of: model.method) { _, _ in model.refreshPreview(rows: rows, cache: cache) }
    }

    @ViewBuilder
    private var scrollingBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let batch = runningBatch { progress(batch) } else { choosing }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var pinnedFooter: some View {
        if runningBatch != nil {
            progressFooter
        } else {
            footer(disabled: model.picks(rows).isEmpty)
        }
    }

    // MARK: - Choosing

    @ViewBuilder
    private var choosing: some View {
        let picks = model.picks(rows)
        eyebrow(Copy.Videos.runEyebrow)
        if picks.isEmpty {
            title(Copy.Videos.runEmptyTitle)
            Text(Copy.Videos.runEmptyBody)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, CicadaTheme.spacingSM)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                wantBlurb(Copy.Videos.wantTranscriptName, Copy.Videos.wantTranscriptBlurb)
                wantBlurb(Copy.Videos.wantWatchName, Copy.Videos.wantWatchBlurb)
            }
            .padding(.top, CicadaTheme.scaled(20))
            let unread = VideoRunModel.rows(rows, in: .unread).count
            if unread > 0 {
                TextButton(title: Copy.Videos.selectAllUnread(unread)) { model.selectAllUnread(rows) }
                    .padding(.leading, -CicadaTheme.scaled(10))
                    .padding(.top, CicadaTheme.spacingMD)
            }
        } else {
            title(Copy.Videos.runTitle(picks.count))
            VStack(spacing: 0) {
                ForEach(picks, id: \.row.id) { pick in pickRow(pick.row, want: pick.want) }
            }
            .padding(.top, CicadaTheme.spacingMD)
            sizeAndHow
                .padding(.top, CicadaTheme.scaled(20))
            promptPreview
                .padding(.top, CicadaTheme.scaled(20))
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "desktopcomputer")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(WatchLeavesMacNote.text())
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.top, CicadaTheme.spacingMD)
        }
    }

    private func eyebrow(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.bottom, CicadaTheme.spacingSM)
    }

    private func title(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.displayFont(size: 22))
            .tracking(CicadaTheme.displayTracking(size: 22))
            .foregroundStyle(CicadaTheme.textPrimary)
            .monospacedDigit()
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityAddTraits(.isHeader)
    }

    private func wantBlurb(_ name: String, _ blurb: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            Text(name).font(CicadaTheme.font(size: 13, weight: .medium)).foregroundStyle(CicadaTheme.textPrimary)
            Text(blurb)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func pickRow(_ row: VideoRow, want: VideoWant) -> some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            VideoThumb(preview: row.item.preview, durationS: row.item.durationS, width: 64, height: 36)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(row.item.title.isEmpty ? row.item.url : row.item.title)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                VideoChannelLine(item: row.item)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Text(VideoSize.of(want: want, seconds: row.item.durationS).word)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            Menu {
                Button { model.set(row, want: .transcript) } label: {
                    menuLabel(Copy.Videos.wantTranscriptName, VideoSize.of(want: .transcript, seconds: row.item.durationS).word,
                              checked: want == .transcript)
                }
                Button { model.set(row, want: .watch) } label: {
                    menuLabel(Copy.Videos.wantWatchName, VideoSize.of(want: .watch, seconds: row.item.durationS).word,
                              checked: want == .watch)
                }
                Divider()
                Button(Copy.Videos.removeFromQueue) {
                    Task { if let sentence = await cache.remove(key: row.state.key) { store.toast = sentence } }
                    model.toggle(row)
                }
                .disabled(!row.state.isQueued)
                .help(row.state.isQueued ? Copy.Videos.removeHelp : Copy.Videos.notInQueueYet)
            } label: {
                Text(want == .watch ? Copy.Videos.wantWatchName : Copy.Videos.wantTranscriptName)
                    .font(CicadaTheme.font(size: 12, weight: .medium))
            }
            .menuStyle(.button)
            .fixedSize()
            .help(Copy.Videos.itemMenuHelp)
        }
        .frame(height: CicadaTheme.scaled(RowMetrics.twoLine))
    }

    private func menuLabel(_ name: String, _ size: String, checked: Bool) -> some View {
        HStack {
            if checked { Image(systemName: "checkmark") }
            Text(name + " · " + size)
        }
    }

    private var sizeAndHow: some View {
        let size = model.size(rows)
        return HStack(alignment: .top, spacing: CicadaTheme.scaled(24)) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Videos.sizeLabel)
                Text(size.line)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .monospacedDigit()
                if let minutes = size.minutesLine {
                    Text(minutes).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Videos.howLabel)
                Picker(Copy.Videos.howLabel, selection: Binding(get: { model.method }, set: { model.method = $0 })) {
                    Text(Copy.Videos.howAuto).tag(VideoMethod.auto)
                    Text(Copy.Videos.howCaptions).tag(VideoMethod.captions)
                    Text(Copy.Videos.howLink).tag(VideoMethod.link)
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .fixedSize()
                .help(model.method == .link ? Copy.Videos.howLinkHelp : Copy.Videos.howLabel)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var promptPreview: some View {
        HStack {
            SectionLabel(Copy.Videos.promptLabel)
            Spacer()
            TextButton(title: model.promptExpanded ? Copy.Videos.showLess : Copy.Videos.showAll) {
                model.promptExpanded.toggle()
            }
        }
        promptBox(model.previewPrompt ?? "", collapsed: !model.promptExpanded)
    }

    private func promptBox(_ text: String, collapsed: Bool) -> some View {
        Text(text)
            .font(CicadaTheme.font(size: 12))
            .foregroundStyle(CicadaTheme.textSecondary)
            .lineLimit(collapsed ? 5 : nil)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(40), alignment: .topLeading)
            .padding(CicadaTheme.spacingMD)
            .overlay(alignment: .bottom) {
                if collapsed {
                    LinearGradient(colors: [CicadaTheme.bgBase.opacity(0), CicadaTheme.bgBase],
                                   startPoint: .top, endPoint: .bottom)
                        .frame(height: CicadaTheme.scaled(18))
                        .allowsHitTesting(false)
                }
            }
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }

    private func footer(disabled: Bool) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            PrimaryActionButton(title: Copy.Videos.copyForAgent) { copyForAgent() }
                .keyboardShortcut(.defaultAction)
                .disabled(disabled || model.isCopying)
                .help(Copy.Videos.copyForAgentHelp)
            KeyHint("⏎")
            Spacer()
            if !disabled {
                TextButton(title: Copy.Videos.clearSelection) { model.clearSelection() }
            }
        }
        .padding(.top, CicadaTheme.scaled(24))
    }

    private func copyForAgent() {
        Task {
            let sentence = await model.copyForAgent(rows: rows, cache: cache) { prompt in
                AppPasteboard.copy(prompt)
                agentGot = prompt
            }
            store.toast = sentence ?? Copy.Videos.copied
        }
    }

    // MARK: - Progress

    @ViewBuilder
    private func progress(_ batch: VideoBatch) -> some View {
        let members = VideoRunProgress.members(batch: batch, rows: rows)
        eyebrow(batch.createdAt.flatMap { VideoWords.recordedTime($0) }.map(Copy.Videos.startedAt) ?? Copy.Videos.runEyebrow)
        title(Copy.Videos.recordedOf(batch.done, batch.total))
        VideoRunMeter(meter: VideoRunProgress.meter(batch))
            .padding(.top, CicadaTheme.spacingMD)
            .accessibilityLabel(Copy.Videos.meter)
            .accessibilityValue(Copy.Videos.meterHelp(done: batch.done, total: batch.total))
            .help(Copy.Videos.meterHelp(done: batch.done, total: batch.total))
        let line = VideoRunProgress.meterLine(batch)
        if !line.isEmpty {
            Text(line)
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.top, CicadaTheme.spacingSM)
        }
        VStack(alignment: .leading, spacing: 0) {
            if members.count <= VideoRunProgress.segmentLimit {
                ForEach(members) { member in progressRow(member) }
            } else {
                ForEach(VideoRunProgress.groups(members)) { group in
                    SectionLabel(Copy.Videos.group(group.title, group.members.count))
                        .padding(.top, CicadaTheme.spacingMD)
                        .padding(.bottom, CicadaTheme.spacingXS)
                    ForEach(group.members) { member in progressRow(member) }
                }
            }
        }
        .padding(.top, CicadaTheme.spacingMD)
        DisclosureGroup(isExpanded: $agentGotOpen) {
            promptBox(agentGot ?? "", collapsed: false).padding(.top, CicadaTheme.spacingSM)
        } label: {
            Text(Copy.Videos.whatYourAgentGot).font(CicadaTheme.font(size: 13)).foregroundStyle(CicadaTheme.textPrimary)
        }
        .padding(.top, CicadaTheme.spacingMD)
        .task(id: agentGotOpen) { if agentGotOpen, agentGot == nil { agentGot = await cache.prompt(count: nil, method: nil) } }
    }

    private var progressFooter: some View {
        HStack {
            Text(Copy.Videos.sleepReadsThese).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            Spacer()
            TextButton(title: Copy.Videos.copyPromptAgain, help: Copy.Videos.copyPromptAgainHelp) {
                Task {
                    guard let prompt = await cache.prompt(count: nil, method: nil) else { return }
                    AppPasteboard.copy(prompt)
                    agentGot = prompt
                    store.toast = Copy.Videos.copied
                }
            }
        }
        .padding(.top, CicadaTheme.spacingMD)
    }

    private func progressRow(_ member: VideoRunMember) -> some View {
        VideoRunProgressRow(member: member, openRecord: { openRecord(member) }, tryAgain: {
            Task { if let sentence = await cache.retry(key: member.row.state.key) { store.toast = sentence } }
        })
    }

    private func openRecord(_ member: VideoRunMember) {
        guard let episode = member.row.state.episodeId else { return }
        provenance.open(ReaderTarget(episode: episode, subjectId: member.row.item.mediaEntityId,
                                     knownTitle: member.row.item.title, knownHarness: member.row.state.recordedBy))
    }
}

/// One segment per video up to ten, a continuous bar above — always with its noun beside it (the title says
/// "2 of 5 recorded").
struct VideoRunMeter: View {
    let meter: VideoRunProgress.Meter

    var body: some View {
        switch meter {
        case .segments(let count, let filled):
            HStack(spacing: CicadaTheme.scaled(4)) {
                ForEach(0..<count, id: \.self) { i in
                    Capsule().fill(i < filled ? CicadaTheme.textSecondary : CicadaTheme.bgSelected)
                        .frame(height: CicadaTheme.scaled(4))
                }
            }
        case .continuous(let fraction):
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(CicadaTheme.bgSelected)
                    Capsule().fill(CicadaTheme.textSecondary).frame(width: geo.size.width * min(max(fraction, 0), 1))
                }
            }
            .frame(height: CicadaTheme.scaled(4))
        }
    }
}

/// A run member in the card: a status glyph, its frame, the title over what was asked for or what came of it, and the
/// trailing fact — the recorder's mark and time (hover: "Open the record ›"), *Try again*, who picked it up, or
/// "Waiting".
struct VideoRunProgressRow: View {
    let member: VideoRunMember
    let openRecord: () -> Void
    let tryAgain: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            Image(systemName: glyph)
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(member.status == .failed ? CicadaTheme.warning : CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(16))
                .accessibilityHidden(true)
            VideoThumb(preview: member.row.item.preview, durationS: member.row.item.durationS, width: 56, height: 32)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(member.row.item.title.isEmpty ? member.row.item.url : member.row.item.title)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Text(VideoRunProgress.line(member))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            trailing
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(height: CicadaTheme.scaled(RowMetrics.twoLine))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(hovering && member.status == .recorded ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
    }

    private var glyph: String {
        switch member.status {
        case .recorded: "checkmark"
        case .failed: "exclamationmark.triangle"
        case .pickedUp: "circle.lefthalf.filled"
        case .waiting: "circle"
        }
    }

    @ViewBuilder
    private var trailing: some View {
        switch member.status {
        case .recorded:
            if hovering, member.row.state.episodeId != nil {
                Button(Copy.Videos.openRecord, action: openRecord)
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .help(Copy.Videos.openRecordHelp)
            } else if let by = member.row.state.recordedBy {
                HStack(spacing: CicadaTheme.spacingXS) {
                    OriginMark(origin: by, size: CicadaTheme.scaled(12))
                    Text(Copy.Videos.recordedBy(VideoWords.agentName(by), at: VideoWords.recordedTime(member.row.state.recordedAt)))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        case .failed:
            NeutralButton(title: Copy.Videos.tryAgain, size: .compact, action: tryAgain)
        case .pickedUp:
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.Videos.pickedUpByLead)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                if let by = member.row.state.claimedBy { OriginMark(origin: by, size: CicadaTheme.scaled(12)) }
                Text(VideoWords.agentName(member.row.state.claimedBy))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        case .waiting:
            Text(Copy.Videos.rowWaiting).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
