import Foundation

/// Wire mirror of `api/models/schemas.py::OwnerSettingsResponse` (G117).
/// `CamelModel` on the backend already emits camelCase, so the default
/// `Codable` synthesis (no `keyDecodingStrategy`) matches the wire exactly.
/// Every field but `name`/`observer` is optional so an older backend
/// payload — or a bank that has never onboarded — still decodes.
struct OwnerSettings: Codable, Equatable {
    var name: String
    var handle: String?
    var email: String?
    /// R1's resolved value: `"owner"` on a fresh bank, the legacy
    /// `"rodrigo"` on a pre-G117 bank until the name is set, else the
    /// name-derived slug. Always non-empty.
    var observer: String
    var entityId: String?
}
