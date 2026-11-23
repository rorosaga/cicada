import Foundation

/// 2026-11-23 (owner: "show how the reason evolves … by a glance we can see the app, the reason, how long ago it was")
/// — a bookmark's reasons as one history, newest first: every answer as it stands now and every wording an edit
/// replaced (`before`), each with where it was given and when. The newest is the `current` card; the rest fade.
enum ReasonTimeline {
    struct Entry: Equatable, Identifiable {
        let id: String
        /// What the card reads: the reasons' names, then the person's own words.
        let text: String
        let origin: String?
        let date: Date?
        /// The answer this is (its `at`, what an edit names) — nil for an earlier wording, which is history only.
        let answerAt: String?
        let record: SavedWhyRecord?
        let held: Bool
        let edited: Bool
        let earlier: Bool
        let resave: Bool
    }

    /// `answers` oldest first (the wire's order); `bookmarkOrigin` is where the bookmark itself was saved — the one
    /// place an answer from before `via` was recorded can be said to come from, and only the first wording of the
    /// first answer (the panel only ever asked over the browser; a later or edited one may have come from the app).
    static func entries(_ answers: [SavedWhyRecord], bookmarkOrigin: String?,
                        project: (String) -> String = { $0 }) -> [Entry] {
        var out: [Entry] = []
        for (index, record) in answers.enumerated() {
            let versions = record.before ?? []
            for (v, earlier) in versions.enumerated() {
                let fallback = index == 0 && v == 0 ? bookmarkOrigin : nil
                out.append(Entry(id: "\(record.at ?? "\(index)")#\(v)",
                                 text: words(labels: earlier.labels, project: earlier.project.map(project),
                                             text: earlier.text),
                                 origin: earlier.via ?? fallback, date: earlier.at.flatMap(ISODate.parse),
                                 answerAt: nil, record: nil, held: false, edited: v > 0, earlier: true,
                                 resave: index > 0))
            }
            let fallback = index == 0 && versions.isEmpty && record.editedAt == nil && !record.isHeld
                ? bookmarkOrigin : nil
            let when = (record.isHeld ? record.at : record.editedAt ?? record.at).flatMap(ISODate.parse)
            out.append(Entry(id: record.at ?? "\(index)",
                             text: words(labels: record.labels, project: record.project.map(project),
                                         text: record.text),
                             origin: record.via ?? fallback, date: when, answerAt: record.at, record: record,
                             held: record.isHeld, edited: record.editedAt != nil || !versions.isEmpty,
                             earlier: false, resave: index > 0))
        }
        // Newest first; an undated entry keeps its place after the dated ones.
        return out.enumerated().sorted { a, b in
            switch (a.element.date, b.element.date) {
            case let (x?, y?): return x != y ? x > y : a.offset > b.offset
            case (.some, nil): return true
            case (nil, .some): return false
            case (nil, nil): return a.offset > b.offset
            }
        }.map(\.element)
    }

    static func words(labels: [String], project: String?, text: String?) -> String {
        let names = (labels + [project].compactMap { $0 }).joined(separator: " · ")
        let said = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return [names, said].filter { !$0.isEmpty }.joined(separator: " — ")
    }
}
