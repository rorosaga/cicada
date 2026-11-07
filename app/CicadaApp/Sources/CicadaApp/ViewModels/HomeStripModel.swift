import Foundation
import Observation

/// G132 phase 2 (ruling 51a; owner 2026-10-29: "Sleep page on the app should show the selected device running
/// consolidation and you should be able to easily switch") — the Sleep page's strip of the memory's home: who runs
/// consolidation now, every other device, and the two acts — make another the home, or take over a lost one. Polled
/// while the page shows (`GET /sync/home`), held in memory, never a Store domain; a failed poll keeps the last answer
/// (never blank). Owned by `SleepViewModel`, so no file under Views/Sleep reaches `APIClient` (R-Z10).
@Observable
@MainActor
final class HomeStripModel {
    private(set) var overview: HomeOverview?
    /// The sentence of the last refusal or failure, shown under the strip until the page's next successful slow poll
    /// (`load(clearingProblem: true)`, from `SleepViewModel.loadMachines`) — never cleared by a move's own follow.
    private(set) var problem: String?
    /// The take-over preview the person is being shown (its `behind` is what a confirm sends).
    private(set) var preview: TakeOverPreview?
    private(set) var busy = false
    /// The move this computer asked for (the device that will be the home), kept until a poll shows that device as
    /// the home or the follow runs out — so on a copy, whose own answer may not know the home's progress, the strip
    /// still says it is moving and offers no second move.
    private(set) var movingTo: String?
    /// The move's words as the home answered the request (the 202's `moving`), shown while `movingTo` is set and the
    /// poll has none of its own.
    private(set) var movingWords: HomeOverview.Words?

    private let fetch: () async throws -> HomeOverview
    private let move: (String) async throws -> HomeMoveAnswer
    private let fetchPreview: () async throws -> TakeOverPreview
    private let confirmTakeOver: (Int) async throws -> Void
    private let followTries: Int
    private let followEvery: TimeInterval

    init(fetch: @escaping () async throws -> HomeOverview = { try await APIClient.shared.fetchHome() },
         move: @escaping (String) async throws -> HomeMoveAnswer = { try await APIClient.shared.moveHome(to: $0) },
         fetchPreview: @escaping () async throws -> TakeOverPreview = {
             try await APIClient.shared.fetchTakeOverPreview()
         },
         confirmTakeOver: @escaping (Int) async throws -> Void = { try await APIClient.shared.takeOver(behind: $0) },
         followTries: Int = CicadaTiming.homeMoveFollowTries,
         followEvery: TimeInterval = CicadaTiming.homeMoveFollow) {
        self.fetch = fetch
        self.move = move
        self.fetchPreview = fetchPreview
        self.confirmTakeOver = confirmTakeOver
        self.followTries = followTries
        self.followEvery = followEvery
    }

    /// Whether the strip draws at all: only when this memory is shared with another device (one computer sees
    /// nothing new — "unset or off, nothing changes").
    var isShown: Bool { overview?.shared == true && overview?.home != nil }

    /// A move is under way: the home says so, or this computer asked for one that has not landed yet.
    var isMoving: Bool { movingTo != nil || overview?.isMoving == true }

    /// What the strip says about the move: the poll's own words, else the home's answer to the request.
    var movingLine: String? {
        if let text = overview?.moving?.text, !text.isEmpty { return text }
        return movingTo != nil ? movingWords?.text : nil
    }

    /// One poll. `clearingProblem` (the page's slow poll only): a successful answer clears the last refusal.
    func load(clearingProblem: Bool = false) async {
        if let next = try? await fetch() {
            overview = next
            if clearingProblem { problem = nil }
        }
    }

    func makeHome(_ device: HomeOverview.Device) async {
        guard movingTo == nil else { return }
        busy = true
        defer { busy = false }
        do {
            let answer = try await move(device.id)
            problem = nil
            movingTo = device.id
            movingWords = answer.moving
        } catch {
            problem = Self.sentence(error)
            await load()
            return
        }
        await follow(until: device.id)
    }

    /// A move takes seconds: the strip asks again every couple of seconds until the poll names the new home (or no
    /// move is under way for a home that is not this one), else until the tries run out — then the page's slow poll
    /// takes over. A failed ask keeps the last answer (this computer's own backend may be starting again).
    private func follow(until target: String?) async {
        defer {
            movingTo = nil
            movingWords = nil
        }
        for _ in 0..<followTries {
            await load()
            if let target, overview?.home?.id == target, overview?.isMoving != true { return }
            if target == nil, overview?.isMoving != true { return }
            try? await Task.sleep(for: .seconds(followEvery))
        }
    }

    /// Ask how far behind this computer is, so the confirmation shows it first.
    func askTakeOver() async {
        busy = true
        defer { busy = false }
        do {
            let answer = try await fetchPreview()
            if answer.possible {
                preview = answer
                problem = nil
            } else {
                preview = nil
                problem = answer.text ?? Copy.MemoryHome.failed
            }
        } catch {
            problem = Self.sentence(error)
        }
    }

    func cancelTakeOver() { preview = nil }

    /// The person confirmed the number they were shown. Takes `behind` itself — never reads `preview`, which the
    /// dialog's dismissal clears before this runs (review of #570).
    func takeOver(behind: Int) async {
        preview = nil
        busy = true
        defer { busy = false }
        do {
            try await confirmTakeOver(behind)
            problem = nil
        } catch {
            problem = Self.sentence(error)
        }
        await follow(until: nil)
    }

    nonisolated static func sentence(_ error: Error) -> String {
        if case APIError.httpError(_, let raw) = error, let detail = MemoryCopyModel.detail(raw) {
            return detail
        }
        return Copy.MemoryHome.failed
    }
}
