import Foundation
import os

/// G183(d) — the bank a write belongs to. `APIClient` names it on every mutating request (`X-Cicada-Bank`), and the
/// server refuses the write before its handler runs when that bank is no longer the active one
/// (`api/services/bank_binding.py`, `409 {"code": "bank_mismatch"}`). That server check is what keeps a write out of
/// the wrong bank; the Store's serialized switch is only the UX around it.
///
/// The bank is the one the operation STARTED in, never the one on screen when the request leaves: `Store.perform`
/// binds it at admission, a held answer carries the bank it was made in, and a folder scan binds the bank it read its
/// configuration from (`bound(to:_:)`). Work that binds nothing falls back to the bank on screen at send time —
/// which, during a switch, is still the old bank while the server is already on the new one, so even that is refused
/// rather than misfiled.
enum BankScope {
    static let header = "X-Cicada-Bank"

    @TaskLocal static var origin: String?

    private static let screen = OSAllocatedUnfairLock<String?>(initialState: nil)

    /// The bank the app shows — kept by the app's `Store` (its `bank`), read by `APIClient` as the fallback.
    static var onScreen: String? {
        get { screen.withLock { $0 } }
        set { screen.withLock { $0 = newValue } }
    }

    /// Run `work` with every write it makes bound to `bank`.
    static func bound<T>(to bank: String?, _ work: () async throws -> T) async rethrows -> T {
        try await $origin.withValue(bank ?? origin) { try await work() }
    }

    /// The header's value for a request, or nil (a read, or no bank known).
    static func value(method: String, origin: String? = BankScope.origin, onScreen: String? = BankScope.onScreen) -> String? {
        guard ["POST", "PUT", "PATCH", "DELETE"].contains(method.uppercased()),
              let bank = origin ?? onScreen, !bank.isEmpty else { return nil }
        return bank.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_.~")))
            ?? bank
    }

    /// The server's refusal of a write named for a bank that is no longer active.
    static func isMismatch(_ error: (any Error)?) -> Bool {
        guard case .httpError(409, let body)? = error as? APIError,
              let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return object["code"] as? String == "bank_mismatch"
    }
}
