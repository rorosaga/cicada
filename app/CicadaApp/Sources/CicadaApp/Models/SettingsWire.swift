import Foundation

// G139 — the small wire and pure pieces behind You and Privacy & data. Every field optional-with-default so an older
// backend decodes. (Settings defaults, owner 2026-10-22: Advanced, the search rebuild and the link-preview button left
// the app, and their words with them; the routes and the `cicada index` commands stay.)

/// `DELETE /banks/{name}` (R-O19): the roster after the move and where the
/// bank went, relative to the memory folder.
struct BankTrashResult: Decodable {
    let banks: [MemoryBank]
    let active: String?
    let trashedTo: String

    enum CodingKeys: String, CodingKey { case banks, active, trashedTo }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        banks = (try? c.decode([MemoryBank].self, forKey: .banks)) ?? []
        active = try c.decodeIfPresent(String.self, forKey: .active)
        trashedTo = (try? c.decode(String.self, forKey: .trashedTo)) ?? ""
    }
}

/// The You page's edits. `PUT /settings/owner` rewrites and commits the owner's
/// page, so only a real change is ever sent, and never a blank name (the
/// backend 400s on it).
struct OwnerDraft: Equatable {
    var name = ""
    var handle = ""
    var email = ""

    init() {}
    init(_ saved: OwnerSettings) {
        name = saved.name
        handle = saved.handle ?? ""
        email = saved.email ?? ""
    }

    func update(from saved: OwnerSettings?) -> (name: String, handle: String?, email: String?)? {
        func clean(_ s: String) -> String? {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        guard let n = clean(name) else { return nil }
        let h = clean(handle), e = clean(email)
        if let saved, saved.name == n, saved.handle == h, saved.email == e { return nil }
        return (n, h, e)
    }
}
