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
    /// The sentence of the last refusal or failure, shown under the strip until the next poll succeeds.
    private(set) var problem: String?
    /// The take-over preview the person is being shown (its `behind` is what a confirm sends).
    private(set) var preview: TakeOverPreview?
    private(set) var busy = false

    private let fetch: () async throws -> HomeOverview
    private let move: (String) async throws -> Void
    private let fetchPreview: () async throws -> TakeOverPreview
    private let confirmTakeOver: (Int) async throws -> Void

    init(fetch: @escaping () async throws -> HomeOverview = { try await APIClient.shared.fetchHome() },
         move: @escaping (String) async throws -> Void = { try await APIClient.shared.moveHome(to: $0) },
         fetchPreview: @escaping () async throws -> TakeOverPreview = {
             try await APIClient.shared.fetchTakeOverPreview()
         },
         confirmTakeOver: @escaping (Int) async throws -> Void = { try await APIClient.shared.takeOver(behind: $0) }) {
        self.fetch = fetch
        self.move = move
        self.fetchPreview = fetchPreview
        self.confirmTakeOver = confirmTakeOver
    }

    /// Whether the strip draws at all: only when this memory is shared with another device (one computer sees
    /// nothing new — "unset or off, nothing changes").
    var isShown: Bool { overview?.shared == true && overview?.home != nil }

    func load() async {
        if let next = try? await fetch() {
            overview = next
        }
    }

    func makeHome(_ device: HomeOverview.Device) async {
        busy = true
        defer { busy = false }
        do {
            try await move(device.id)
            problem = nil
        } catch {
            problem = Self.sentence(error)
        }
        await follow()
    }

    /// A move takes seconds: the strip asks again every couple of seconds until it is done, not on the page's slow
    /// poll (this computer's own backend may be starting again in between — a failed ask keeps the last answer).
    private func follow() async {
        for _ in 0..<CicadaTiming.homeMoveFollowTries {
            await load()
            if overview?.isMoving != true { return }
            try? await Task.sleep(for: .seconds(CicadaTiming.homeMoveFollow))
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

    func takeOver() async {
        guard let behind = preview?.behind else { return }
        busy = true
        defer { busy = false }
        do {
            try await confirmTakeOver(behind)
            problem = nil
        } catch {
            problem = Self.sentence(error)
        }
        preview = nil
        await follow()
    }

    nonisolated static func sentence(_ error: Error) -> String {
        if case APIError.httpError(_, let raw) = error, let detail = MemoryCopyModel.detail(raw) {
            return detail
        }
        return Copy.MemoryHome.failed
    }
}
