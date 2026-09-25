import Foundation

/// The facts a row is drawn from beyond its runner state — gathered by the host from the Store, the browser watch and
/// `SyncActivity`, so `SetupProgress` stays pure.
struct SetupFacts {
    var channels: [SourceChannel] = []
    var watches: [String: BrowserWatchState] = [:]
    var runs: [String: SyncActivity.Run] = [:]
    /// A dropped export's vendor mark (`SetupRunner.origins`).
    var origins: [FoundItemID: String] = [:]
    var finishedAt: [FoundItemID: Date] = [:]
}

/// Where a row stands in the setup story (rationale-F: "k counts sources that are neither done nor waiting on the
/// person").
enum SetupRowPhase: Equatable { case comingIn, done, needsYou, off }

struct SetupRowSnapshot: Equatable, Identifiable {
    let row: GettingStartedRow
    let model: SourceRowModel
    let phase: SetupRowPhase
    var id: FoundItemID { row.id }
    var cancellable: Bool { if case .syncing(_, _, true) = model.status { return true }; return false }
}

struct SetupSummary: Equatable {
    var comingIn: [SetupRowSnapshot] = []
    var keepingUp: [SetupRowSnapshot] = []
    var newestSync: Date?
}

/// R-OB4 — the one projection. `SetupRunner` is the one store of row state (R-IB14); this turns it, the live runs
/// and the channels into what every surface draws — the Import rows, the topbar's "k still coming in", F-07 and Home's
/// Getting started — through ONE row function, `GettingStartedSourceRows.model`, so no two surfaces can disagree.
/// Main-actor because `ConnectedChannelRow.origin(forChannel:)` (a view's static) is; every caller is a view.
@MainActor
enum SetupProgress {
    static func origin(_ id: FoundItemID, origins: [FoundItemID: String]) -> String {
        switch id {
        case .agent(let agent): agent
        case .browser(let channel), .app(let channel): ConnectedChannelRow.origin(forChannel: channel)
        case .dropped: origins[id] ?? ""
        }
    }

    static func snapshots(_ rows: [GettingStartedRow], facts: SetupFacts) -> [SetupRowSnapshot] {
        rows.map { row in
            let channelId = GettingStartedSourceRows.channelId(row.id)
            let run = GettingStartedSourceRows.runKey(row.id).flatMap { facts.runs[$0] }
            let model = GettingStartedSourceRows.model(
                row, origin: origin(row.id, origins: facts.origins),
                channel: channelId.flatMap { id in facts.channels.first { $0.id == id } },
                watch: channelId.flatMap { facts.watches[$0] }, run: run, finishedAt: facts.finishedAt[row.id])
            return SetupRowSnapshot(row: row, model: model, phase: phase(row.state, status: model.status))
        }
    }

    static func phase(_ state: FoundRowState, status: SourceRowStatus) -> SetupRowPhase {
        if status.isSyncing { return .comingIn }
        switch state {
        case .working: return .comingIn
        case .on: return .done
        case .needsAction, .failed: return .needsYou
        case .off: return .off
        }
    }

    static func stillComingIn(_ snapshots: [SetupRowSnapshot]) -> Int { snapshots.filter { $0.phase == .comingIn }.count }

    /// F-07 — what still runs; what is done and keeps up on its own (a one-time read and an import do not), and the
    /// newest last sync among those.
    static func summary(_ snapshots: [SetupRowSnapshot], keepsUp: (FoundItemID) -> Bool) -> SetupSummary {
        let keeping = snapshots.filter { $0.phase == .done && keepsUp($0.id) }
        let newest = keeping.compactMap { snapshot -> Date? in
            if case .synced(let date) = snapshot.model.status { return date }
            return nil
        }.max()
        return SetupSummary(comingIn: snapshots.filter { $0.phase == .comingIn }, keepingUp: keeping, newestSync: newest)
    }

    /// The line a page opens with: the newest row that finished after the page appeared.
    static func arrival(_ snapshots: [SetupRowSnapshot], finishedAt: [FoundItemID: Date],
                        since: Date) -> SetupRowSnapshot? {
        snapshots.filter { $0.phase == .done }
            .compactMap { s in finishedAt[s.id].flatMap { $0 > since ? (s, $0) : nil } }
            .max { $0.1 < $1.1 }?.0
    }

    /// A browser keeps up (the watch); an app source when its driver says so; an agent or an import does not.
    static func keepsUp(_ id: FoundItemID, apps: [String: AppSourceDriver]) -> Bool {
        switch id {
        case .browser: true
        case .app(let app): apps[app]?.keepsUp ?? false
        case .agent, .dropped: false
        }
    }
}
