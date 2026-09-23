import Foundation

/// Which Sources card a conversation belongs to (R-SU18's fallback): its
/// harness's card (`harness:<name>`), else the card whose origins include the
/// episode's origin (a chat export). `nil` when neither is listed — the caller
/// shows the grid rather than a guessed neighbour.
enum ConversationSource {
    static func sourceId(harness: String?, origin: String?, rows: [SourceOverview]) -> String? {
        if let harness, !harness.isEmpty, let row = rows.first(where: { $0.harness == harness }) { return row.id }
        if let origin, !origin.isEmpty, let row = rows.first(where: { $0.origins.contains(origin) }) { return row.id }
        return nil
    }
}
