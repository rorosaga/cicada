import Foundation
import Observation

/// Backs the memory-bank "Projects" dropdown (M6) and the import target selector
/// (M7). Thin projection over `Store.banks` (§5.5): `banks`/`activeName` read
/// straight from the snapshot. Mutating actions (`activate`/`create`/`rename`/
/// `duplicate`) still go through `APIClient` directly — they aren't reads —
/// then ask the Store to refresh `.banks` (which, for `activate`, re-hydrates
/// every other domain from the new bank's cache; see `Store.refresh`).
@Observable
@MainActor
final class BanksViewModel {
    private let store: Store

    var errorMessage: String?

    init(store: Store) {
        self.store = store
    }

    var banks: [MemoryBank] { store.banks.value?.banks ?? [] }
    var activeName: String? {
        store.banks.value?.active ?? banks.first(where: { $0.active })?.name
    }
    var isLoading: Bool { store.banks.isEmpty && store.banks.isRefreshing }

    /// The currently-active bank object, if present in the roster.
    var activeBank: MemoryBank? {
        if let activeName, let match = banks.first(where: { $0.name == activeName }) {
            return match
        }
        return banks.first(where: { $0.active })
    }

    func load() async {
        errorMessage = nil
        await store.refresh([.banks])
        if store.banks.value == nil {
            errorMessage = store.toast
        }
    }

    /// Switch the active bank, optimistically (§5.4): `store.bank` moves and
    /// every domain re-hydrates from the target bank's disk cache before the
    /// POST is sent, so the app repaints on the click. A failure re-hydrates
    /// the previous bank and restores the roster's active flag. Returns true
    /// on success so the caller can chain a `graphVM.loadGraph()`.
    @discardableResult
    func activate(_ name: String) async -> Bool {
        errorMessage = nil
        let ok = await store.perform(ActivateBank(name: name))
        if !ok { errorMessage = store.toast }
        return ok
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

    /// Rename a bank in place, then reload. Returns the backend **slug** the bank
    /// was rekeyed under on success (e.g. "Original V1" → "original-v1"), or nil
    /// on failure. If the renamed bank was the active one, the backend repoints
    /// `active`, and `load()` picks that up — but callers should still use the
    /// returned slug for any immediate follow-up activate/import.
    @discardableResult
    func rename(name: String, newName: String) async -> String? {
        let trimmed = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != name else { return nil }
        errorMessage = nil
        do {
            let slug = try await APIClient.shared.renameBank(name: name, newName: trimmed)
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
