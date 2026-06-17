import Foundation
import Observation

/// Backs the memory-bank "Projects" dropdown (M6) and the import target selector
/// (M7). Loads banks from `GET /banks`, tracks the active one, and drives
/// switch / create / duplicate. Mutating actions reload the roster so the
/// dropdown reflects the new state; the caller is responsible for reloading the
/// graph after an activate (`graphVM.loadGraph()`).
@Observable
@MainActor
final class BanksViewModel {
    var banks: [MemoryBank] = []
    var activeName: String?
    var isLoading = false
    var errorMessage: String?

    /// The currently-active bank object, if present in the roster.
    var activeBank: MemoryBank? {
        if let activeName, let match = banks.first(where: { $0.name == activeName }) {
            return match
        }
        return banks.first(where: { $0.active })
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            let resp = try await APIClient.shared.fetchBanks()
            banks = resp.banks
            activeName = resp.active ?? resp.banks.first(where: { $0.active })?.name
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    /// Switch the active bank, then reload the roster. Returns true on success
    /// so the caller can chain a `graphVM.loadGraph()`.
    @discardableResult
    func activate(_ name: String) async -> Bool {
        errorMessage = nil
        do {
            try await APIClient.shared.activateBank(name: name)
            await load()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    /// Create a new empty bank, then reload. Returns the backend **slug** the
    /// bank was keyed under (e.g. "My Project" → "my-project") on success, or
    /// nil on failure. Callers MUST use the returned slug for any subsequent
    /// `activate`/`import` — the raw typed name 404s once it differs from its
    /// slug.
    @discardableResult
    func create(name: String, description: String? = nil) async -> String? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        errorMessage = nil
        do {
            let slug = try await APIClient.shared.createBank(name: trimmed, description: description)
            await load()
            return slug
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    /// "Save as…" — duplicate the given bank under a new name, then reload.
    @discardableResult
    func duplicate(from name: String, newName: String) async -> Bool {
        let trimmed = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        errorMessage = nil
        do {
            try await APIClient.shared.duplicateBank(name: name, newName: trimmed)
            await load()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}
