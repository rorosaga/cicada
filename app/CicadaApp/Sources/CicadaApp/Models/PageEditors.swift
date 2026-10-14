import Foundation
import Observation

// G198 (owner ruling 2026-10-14) — the agents the person lets edit a page's words directly: `GET/PUT
// /settings/editors`, a machine-wide file the backend keeps outside every bank. Not a Store domain (no ETag): read
// when Settings → Agents appears, held in memory, a toggle written optimistically and rolled back on refusal.

struct PageEditor: Decodable, Equatable, Identifiable {
    var harness: String
    var label: String
    var since: String?

    var id: String { harness }

    enum CodingKeys: String, CodingKey { case harness, label, since }

    init(harness: String, label: String, since: String? = nil) {
        self.harness = harness
        self.label = label
        self.since = since
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        harness = try c.decodeIfPresent(String.self, forKey: .harness) ?? ""
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? harness
        since = try c.decodeIfPresent(String.self, forKey: .since)
    }
}

struct PageEditorsResponse: Decodable, Equatable {
    var trusted: [PageEditor]
    var candidates: [PageEditor]
    /// The agents on the list while the person never changed it (owner, 2026-10-14: the person's own coding agents),
    /// named by the backend so the app never hardcodes a provider.
    var defaults: [PageEditor]
    /// Whether the person ever changed the list; until then `defaults` are what is trusted.
    var customized: Bool

    enum CodingKeys: String, CodingKey { case trusted, candidates, defaults, customized }

    init(trusted: [PageEditor] = [], candidates: [PageEditor] = [], defaults: [PageEditor] = [],
         customized: Bool = false) {
        self.trusted = trusted
        self.candidates = candidates
        self.defaults = defaults
        self.customized = customized
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        trusted = try c.decodeIfPresent([PageEditor].self, forKey: .trusted) ?? []
        candidates = try c.decodeIfPresent([PageEditor].self, forKey: .candidates) ?? []
        defaults = try c.decodeIfPresent([PageEditor].self, forKey: .defaults) ?? []
        customized = try c.decodeIfPresent(Bool.self, forKey: .customized) ?? false
    }

    func isTrusted(_ harness: String) -> Bool { trusted.contains { $0.harness == harness } }

    func isDefault(_ harness: String) -> Bool { defaults.contains { $0.harness == harness } }

    /// The rows Settings lists: every local agent the person could allow, plus any already allowed that the
    /// backend no longer lists as a candidate (so it can still be turned off).
    var rows: [PageEditor] {
        candidates + trusted.filter { t in !candidates.contains { $0.harness == t.harness } }
    }

    /// The same response with one agent turned on or off — what the switch shows before the server answers.
    func setting(_ harness: String, on: Bool, today: String) -> PageEditorsResponse {
        var copy = self
        guard isTrusted(harness) != on else { return copy }     // a no-op leaves the list as it was, unset included
        copy.customized = true
        copy.trusted.removeAll { $0.harness == harness }
        if on {
            let label = rows.first { $0.harness == harness }?.label ?? harness
            copy.trusted.append(PageEditor(harness: harness, label: label, since: today))
        }
        return copy
    }
}

/// Settings → Agents → "Edits pages directly". One load, one optimistic write at a time.
@Observable
@MainActor
final class PageEditorsModel {
    struct Deps {
        var load: () async throws -> PageEditorsResponse
        var set: (String, Bool) async throws -> PageEditorsResponse

        static let live = Deps(
            load: { try await APIClient.shared.fetchPageEditors() },
            set: { harness, on in try await APIClient.shared.setPageEditor(harness, trusted: on) })
    }

    private(set) var editors: PageEditorsResponse?
    private(set) var busy: Set<String> = []
    /// The server's sentence when a change was refused or failed; cleared by the next change.
    private(set) var note: String?
    private(set) var loadFailed = false
    @ObservationIgnored private let deps: Deps

    init(deps: Deps = .live) { self.deps = deps }

    func load() async {
        do {
            editors = try await deps.load()
            loadFailed = false
        } catch {
            // Last known good stays (never blank); only a first load that failed says so.
            loadFailed = editors == nil
        }
    }

    func set(_ harness: String, on: Bool, today: String = PageEditorsModel.today()) async {
        guard let before = editors, !busy.contains(harness) else { return }
        note = nil
        editors = before.setting(harness, on: on, today: today)
        busy.insert(harness)
        defer { busy.remove(harness) }
        do {
            editors = try await deps.set(harness, on)
        } catch APIError.httpError(let code, let body) where code == 400 || code == 409 || code == 422 {
            editors = before
            note = ProjectWriteFailure.detail(body) ?? Copy.PageEdits.saveFailed
        } catch {
            editors = before
            note = Copy.PageEdits.saveFailed
        }
    }

    nonisolated static func today() -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }
}
