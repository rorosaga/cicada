import Foundation
import Observation

// G162 — the watch run's brain, pure where it can be: which rows each picker tab shows, what is selected and asked for,
// the size and the prompt, and how a hand-off's progress is laid out. `FeedPage` owns one `VideoRunModel`; the views
// (`VideoPickRow`, `VideoRunCard`) only draw what it decides. Nothing here fetches, downloads or watches a video
// (Track V's rail): the one write is the hand-off, which puts the person's own request in a queue outside the bank.

/// The picker's three tabs. Disjoint, and they add up to every saved video: Not yet read = no record and no queue entry;
/// Queued = queued, picked up or handed back; Read = everything else.
enum VideoPickerTab: String, CaseIterable, Hashable, Identifiable {
    case unread, queued, read

    var id: String { rawValue }

    var label: String {
        switch self {
        case .unread: Copy.Videos.tabUnread
        case .queued: Copy.Videos.tabQueued
        case .read: Copy.Videos.tabRead
        }
    }

    static func of(_ state: VideoStateItem) -> VideoPickerTab {
        if state.isQueued { return .queued }
        return state.state == .none ? .unread : .read
    }

    var emptyMessage: String {
        switch self {
        case .unread: Copy.Videos.nothingUnread
        case .queued: Copy.Videos.nothingQueued
        case .read: Copy.Videos.nothingRead
        }
    }
}

enum VideoRunMode: Equatable { case browse, choosing, progress }

@Observable
@MainActor
final class VideoRunModel {
    private(set) var mode: VideoRunMode = .browse
    var tab: VideoPickerTab = .unread
    /// Feed row ids, in the order picked; the rows stay in list order when drawn.
    private(set) var selected: [String] = []
    /// What each picked video asks for — client state only; Copy for an agent is the one write.
    private(set) var wants: [String: VideoWant] = [:]
    var method: VideoMethod = .auto
    var promptExpanded = false
    private(set) var previewPrompt: String?
    var showsProgressDetail = false
    /// True while the hand-off request is in flight.
    private(set) var isCopying = false

    @ObservationIgnored private var previewTask: Task<Void, Never>?
    @ObservationIgnored private var previewToken = 0

    // MARK: - Joining the Feed to the server's state

    /// The Feed's video items joined to their state, in the Feed's order. A video the state does not name (an older
    /// backend, a page indexed since) has no key to queue and is left out of every picker tab.
    nonisolated static func rows(items: [MediaFeedItem], states: [VideoStateItem]) -> [VideoRow] {
        var byId: [String: VideoStateItem] = [:]
        for s in states { byId[s.id] = s }
        return items.compactMap { item in
            guard FeedKind.of(item) == .video, let state = byId[item.id] else { return nil }
            return VideoRow(item: item, state: state)
        }
    }

    nonisolated static func rows(_ rows: [VideoRow], in tab: VideoPickerTab) -> [VideoRow] {
        rows.filter { VideoPickerTab.of($0.state) == tab }
    }

    /// Tab counts, from the same join the list uses, so a tab and its rows never disagree.
    nonisolated static func counts(_ rows: [VideoRow]) -> [VideoPickerTab: Int] {
        Dictionary(grouping: rows, by: { VideoPickerTab.of($0.state) }).mapValues(\.count)
    }

    func tabs(_ rows: [VideoRow]) -> [TextTab<VideoPickerTab>] {
        let counts = Self.counts(rows)
        return VideoPickerTab.allCases.map { TextTab(id: $0, label: $0.label, count: counts[$0] ?? 0) }
    }

    // MARK: - Mode

    /// The strip's "Choose videos…": the picker, or the run's progress while a hand-off still has videos to record —
    /// the picker's tabs stay reachable from the eyebrow either way.
    func begin(summary: VideoSummary?) {
        if let batch = summary?.batch, batch.total > 0, batch.done < batch.total {
            mode = .progress
        } else {
            mode = .choosing
        }
        promptExpanded = false
    }

    /// The Sleep row's "Choose videos ›" lands in the picker.
    func beginChoosing(tab: VideoPickerTab = .unread) {
        self.tab = tab
        mode = .choosing
    }

    func leave() {
        mode = .browse
        clearSelection()
        previewPrompt = nil
        previewTask?.cancel()
        promptExpanded = false
        showsProgressDetail = false
    }

    /// Any picker tab, tapped from the run's progress, leaves it for the picker.
    func chooseTab(_ tab: VideoPickerTab) {
        self.tab = tab
        if mode != .choosing { mode = .choosing }
    }

    // MARK: - Selection

    func isSelected(_ id: String) -> Bool { selected.contains(id) }

    func toggle(_ row: VideoRow) {
        if let index = selected.firstIndex(of: row.id) {
            selected.remove(at: index)
            wants[row.id] = nil
        } else {
            selected.append(row.id)
            wants[row.id] = Self.defaultWant(row)
        }
    }

    func set(_ row: VideoRow, want: VideoWant) {
        guard selected.contains(row.id) else { return }
        wants[row.id] = want
    }

    func want(for row: VideoRow) -> VideoWant { wants[row.id] ?? Self.defaultWant(row) }

    /// A video already asked for keeps what it asked for; anything else starts as a transcript, the light choice.
    static func defaultWant(_ row: VideoRow) -> VideoWant { row.state.want ?? .transcript }

    func clearSelection() {
        selected = []
        wants = [:]
    }

    /// "Select all 13 not read yet": every row of the Not yet read tab, whatever the current tab shows.
    func selectAllUnread(_ rows: [VideoRow]) {
        for row in Self.rows(rows, in: .unread) where !selected.contains(row.id) {
            selected.append(row.id)
            wants[row.id] = Self.defaultWant(row)
        }
    }

    /// Drop anything the list no longer holds (a video that left the Feed, a bank switch).
    func reconcile(present: Set<String>) {
        selected.removeAll { !present.contains($0) }
        wants = wants.filter { present.contains($0.key) }
    }

    /// The picked rows in list order, with what each asks for.
    func picks(_ rows: [VideoRow]) -> [(row: VideoRow, want: VideoWant)] {
        let chosen = Set(selected)
        return rows.filter { chosen.contains($0.id) }.map { ($0, want(for: $0)) }
    }

    func size(_ rows: [VideoRow]) -> VideoSizeSummary {
        VideoSizeSummary.of(picks(rows).map { ($0.want, $0.row.item.durationS) })
    }

    // MARK: - The eyebrow

    func eyebrow(summary: VideoSummary?) -> String {
        switch mode {
        case .browse: return ""
        case .choosing:
            return Eyebrow.text(Copy.feed, FeedKind.video.label, Copy.Videos.picking,
                                selected.isEmpty ? "" : Copy.Videos.pickedCount(selected.count))
        case .progress:
            guard let batch = summary?.batch else { return Eyebrow.text(Copy.feed, FeedKind.video.label, Copy.Videos.runEyebrow) }
            return Eyebrow.text(Copy.feed, FeedKind.video.label, Copy.Videos.runEyebrow,
                                Copy.Videos.recordedOf(batch.done, batch.total))
        }
    }

    // MARK: - The prompt preview and the one write

    /// How many videos the prompt says are waiting — the server's `handoff` count: every pick the queue leaves queued
    /// (a new, queued or failed row; a pick an agent already claimed stays claimed), plus anything already queued that
    /// was not picked. One case table with the server: `api/tests/fixtures/video_waiting_count.json`.
    func waitingCount(_ rows: [VideoRow]) -> Int {
        let chosen = Set(selected)
        let waitingPicks = rows.filter { chosen.contains($0.id) && $0.state.queueState != .claimed }.count
        let stayingQueued = rows.filter { $0.state.queueState == .queued && !chosen.contains($0.id) }.count
        return waitingPicks + stayingQueued
    }

    /// The text the person is about to copy, asked for and shown BEFORE the write (writes nothing).
    func refreshPreview(rows: [VideoRow], cache: VideoStateCache) {
        previewTask?.cancel()
        guard !selected.isEmpty else { previewPrompt = nil; return }
        previewToken &+= 1
        let token = previewToken
        let count = waitingCount(rows)
        let method = self.method
        previewTask = Task { [weak self] in
            let text = await cache.prompt(count: count, method: method)
            guard !Task.isCancelled, let self, token == self.previewToken else { return }
            self.previewPrompt = text
        }
    }

    /// Copy for an agent: queue every pick (no cap), copy the prompt the server returns, and open the run's progress.
    /// Returns the sentence to show when it failed.
    @discardableResult
    func copyForAgent(rows: [VideoRow], cache: VideoStateCache, copy: (String) -> Void) async -> String? {
        let chosen = picks(rows)
        guard !chosen.isEmpty, !isCopying else { return nil }
        isCopying = true
        defer { isCopying = false }
        let result = await cache.handoff(items: chosen.map { ($0.row.state.key, $0.want) }, method: method)
        switch result {
        case .success(let response):
            copy(response.prompt)
            clearSelection()
            previewPrompt = nil
            mode = .progress
            return nil
        case .failure(let failure):
            return failure.sentence
        }
    }
}

// MARK: - The run's progress

/// How one member of the active hand-off stands, from what the server says about its queue entry: no entry means the
/// record landed (a removed member leaves the batch, so it never reads as done).
enum VideoMemberStatus: Equatable {
    case recorded, pickedUp, waiting, failed
}

struct VideoRunMember: Identifiable, Equatable {
    var row: VideoRow
    var status: VideoMemberStatus
    var id: String { row.id }
    var want: VideoWant { row.state.want ?? .transcript }
}

enum VideoRunProgress {
    /// One segment per video up to this many; a continuous bar above (a 300-video run is not 300 slivers).
    static let segmentLimit = 10

    /// The batch's members in batch order, joined to their rows; a key the Feed no longer holds is left out.
    static func members(batch: VideoBatch, rows: [VideoRow]) -> [VideoRunMember] {
        var byKey: [String: VideoRow] = [:]
        for row in rows { byKey[row.state.key] = row }
        return batch.keys.compactMap { key in
            guard let row = byKey[key] else { return nil }
            return VideoRunMember(row: row, status: status(of: row.state))
        }
    }

    static func status(of state: VideoStateItem) -> VideoMemberStatus {
        switch state.queueState {
        case .queued?: .waiting
        case .claimed?: .pickedUp
        case .failed?: .failed
        case nil: .recorded
        }
    }

    enum Meter: Equatable {
        case segments(count: Int, filled: Int)
        case continuous(fraction: Double)
    }

    static func meter(_ batch: VideoBatch) -> Meter {
        if batch.total <= segmentLimit { return .segments(count: max(batch.total, 1), filled: min(batch.done, batch.total)) }
        return .continuous(fraction: batch.total > 0 ? Double(batch.done) / Double(batch.total) : 0)
    }

    struct Group: Equatable, Identifiable {
        var status: VideoMemberStatus
        var title: String
        var members: [VideoRunMember]
        var id: String { title }
    }

    /// Above ten videos the rows are grouped, the one that needs the person first: Couldn't do, Picked up, Waiting,
    /// Recorded. An empty group is left out.
    static func groups(_ members: [VideoRunMember]) -> [Group] {
        let order: [(VideoMemberStatus, String)] = [
            (.failed, Copy.Videos.groupCouldntDo), (.pickedUp, Copy.Videos.groupPickedUp),
            (.waiting, Copy.Videos.groupWaiting), (.recorded, Copy.Videos.groupRecorded),
        ]
        return order.compactMap { status, title in
            let list = members.filter { $0.status == status }
            return list.isEmpty ? nil : Group(status: status, title: title, members: list)
        }
    }

    /// The second line of a flat row: what was asked for, or what came of it.
    static func line(_ member: VideoRunMember) -> String {
        switch member.status {
        case .recorded: return VideoWords.stateTag(member.row.state.state) ?? Copy.Videos.recordedNoMethod
        case .failed:
            return Copy.Videos.couldntDoLine(want: member.want, reason: VideoWords.failedReason(member.row.state))
        case .pickedUp, .waiting:
            return member.want == .watch ? Copy.Videos.watchWord : Copy.Videos.transcriptWord
        }
    }

    /// The run's list column, third line: the member's live word ("Transcript read", "Couldn't do", "Picked up",
    /// "Recorded, method not given", "Waiting"). A lapsed lease is back in the queue, so it reads Waiting.
    static func listWord(_ member: VideoRunMember) -> String {
        switch member.status {
        case .recorded: return VideoWords.stateTag(member.row.state.state) ?? Copy.Videos.recordedNoMethod
        case .failed: return Copy.Videos.rowCouldntDo
        case .pickedUp: return Copy.Videos.rowPickedUp
        case .waiting: return Copy.Videos.rowWaiting
        }
    }

    /// "1 picked up by an agent · 1 waiting · 1 couldn't be done" from the server's own counts.
    static func meterLine(_ batch: VideoBatch) -> String {
        Copy.Videos.meterLine(claimed: batch.claimed, waiting: batch.waiting, failed: batch.failed)
    }
}
