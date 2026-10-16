import Foundation

/// LinkedIn connections (2026-10-16, G154's pattern) — the wire shapes of `POST /sources/linkedin-connections/preview`
/// and `/import`. The backend enriches people Cicada already has and never adds anyone; these are counts only, never a
/// name.
struct LinkedInConnectionsPreview: Codable, Equatable {
    let connections: Int
    let matched: Int
    let ambiguous: Int
    let unmatched: Int
    let exportedOn: String
}

struct LinkedInConnectionsImport: Codable, Equatable {
    let connections: Int
    let matched: Int
    let sourcesAdded: Int
    let claimsWritten: Int
    let claimsClosed: Int
    let older: Int
}

/// What the Connections section says, in words — pure, so the tests read the sentences the person reads.
enum LinkedInConnectionsWords {
    /// The one sentence under "Connections" (the brief: what it does, in one sentence).
    static let what = "Adds each connection's profile link, company and role to the people already in your memory — it never adds anyone new."
    static let pick = "Choose Connections.csv…"
    static let where_ = "In LinkedIn's data export (Settings → Data privacy → Get a copy of your data), tick Connections; drop the .zip or its Connections.csv."

    static func preview(_ p: LinkedInConnectionsPreview) -> String {
        if p.matched == 0 {
            return "None of your \(p.connections) connections is someone Cicada already knows by that exact name. "
                + "Nothing will be added; they are kept so a person you talk about later is matched then."
        }
        var line = "\(p.matched) of your \(p.connections) connections \(p.matched == 1 ? "is someone" : "are people") "
            + "Cicada already knows."
        if p.ambiguous > 0 { line += " \(p.ambiguous) share a name with more than one person and are left out." }
        return line + " As of \(p.exportedOn)."
    }

    static func confirm(_ p: LinkedInConnectionsPreview) -> String {
        p.matched == 0 ? "Keep for later" : "Add to \(p.matched) \(p.matched == 1 ? "person" : "people")"
    }

    static func done(_ r: LinkedInConnectionsImport) -> String {
        if r.sourcesAdded == 0 && r.claimsWritten == 0 {
            return "Nothing new: memory already has what this export says."
        }
        var line = "Updated \(r.matched) \(r.matched == 1 ? "person" : "people")"
        if r.claimsClosed > 0 { line += ", replacing \(r.claimsClosed) older LinkedIn detail\(r.claimsClosed == 1 ? "" : "s")" }
        return line + "."
    }

    /// The export's own day, sent with a lone `Connections.csv` (its modification date): what the facts are true as
    /// of. A `.zip` carries the date inside, so nothing is sent for it.
    static func exportedOn(fileURL: URL, modified: Date?) -> String? {
        guard fileURL.pathExtension.lowercased() == "csv", let modified else { return nil }
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: modified)
    }
}
