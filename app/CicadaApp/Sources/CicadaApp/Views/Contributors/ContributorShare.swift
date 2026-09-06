import Foundation

/// R-S6 — what the contributors strip *decides*, as pure functions with table
/// tests, so `ContributorsStrip` is a renderer.
///
/// Critique E2: the old section drew one 4 pt bar per author whose width was
/// `commitCount / totalCommits`, with no label, no tick and no percentage,
/// sitting directly under two numbers that were **entities** and **files**.
/// Three scales in one card, none of them named. The replacement is a single
/// stacked bar with one scale that the page states in words — *share of
/// entities written* — and these functions are that scale.
///
/// Entities, not commits: a commit is an implementation detail of how Sleep
/// batches its writes (one cycle commits hundreds of pages at once, and G85
/// splits decay into a second commit of its own), while an entity page is the
/// unit of memory a person actually recognises.
enum ContributorShare {

    /// One slice of the bar and its chip. `contributor` is nil for the folded
    /// tail — there is no single author behind it, so it opens no drill-down
    /// and wears no mark.
    struct Segment: Identifiable {
        /// The `Cicada-Author` trailer, verbatim; `""` for the tail. Kept
        /// beside `displayName` because the chip's `.help()` shows the full id
        /// (critique E3: a long model id is elided in the chip, and hover is
        /// where the whole thing has to remain readable).
        let author: String
        let displayName: String
        let entityCount: Int
        /// Share of all attributed entities, in `0...1`. Never NaN: a bank
        /// whose authors have written no entity pages yields no segments at
        /// all rather than a division by zero (see `segments`).
        let fraction: Double
        let contributor: Contributor?

        var id: String { contributor == nil ? "__remainder__" : author }
        var isRemainder: Bool { contributor == nil }
    }

    /// Default number of rendered segments. Six chips is what fits on one line
    /// at ⌘+ in a two-column window before the row wraps to a second line.
    static let defaultLimit = 6

    /// Ordered by entity count descending (ties broken by author, so the strip
    /// is stable across refreshes rather than reordering on every SSE bump).
    ///
    /// **`limit` counts the rendered segments, remainder included** — above it,
    /// the first `limit - 1` are named and everything after folds into one tail
    /// segment, so `segments(_:limit:).count <= limit` always holds and the
    /// fractions still sum to 1.
    ///
    /// An author with zero entity pages is not a slice of a bar about entity
    /// pages, so it is dropped rather than drawn as a 0 % chip; a bank where
    /// *every* author is in that state returns `[]`, and the strip draws the
    /// empty track with `ContributorSummary`'s sentence still under it. `0/0`
    /// is not `0.0` — the NaN width that would follow is exactly the kind of
    /// silent wrong-looking bar E2 is about.
    ///
    /// **`[]` here is not the strip's empty state.** That bank still has
    /// attributed commits (a fresh install's `cicada`-authored `State
    /// snapshot`s are the canonical case), so `ContributorsStrip` branches its
    /// "No attributed commits yet." on `contributors` and lets `content` render
    /// with no segments; `sentence` then names the maintenance that really
    /// wrote it. Reading emptiness off this function instead printed a false
    /// claim about the repo.
    static func segments(_ contributors: [Contributor], limit: Int = defaultLimit) -> [Segment] {
        guard limit > 0 else { return [] }
        let ranked = contributors
            .filter { $0.entityCount > 0 }
            .sorted { a, b in
                a.entityCount == b.entityCount ? a.author < b.author : a.entityCount > b.entityCount
            }
        let total = ranked.reduce(0) { $0 + $1.entityCount }
        guard total > 0 else { return [] }

        func named(_ c: Contributor) -> Segment {
            Segment(author: c.author,
                    displayName: ContributorIdentity.displayName(author: c.author,
                                                                 kind: ContributorIdentity.kind(of: c)),
                    entityCount: c.entityCount,
                    fraction: Double(c.entityCount) / Double(total),
                    contributor: c)
        }

        guard ranked.count > limit else { return ranked.map(named) }
        let head = ranked.prefix(limit - 1).map(named)
        let tail = ranked.dropFirst(limit - 1)
        let tailEntities = tail.reduce(0) { $0 + $1.entityCount }
        return head + [Segment(author: "",
                               displayName: "\(UsageFormat.count(tail.count)) others",
                               entityCount: tailEntities,
                               fraction: Double(tailEntities) / Double(total),
                               contributor: nil)]
    }
}

/// The one sentence under the bar. Replaces nothing — the old section had no
/// sentence at all, which is why a reader had to add up eleven rows to answer
/// "who wrote this?".
enum ContributorSummary {

    /// Names only what the record actually says. A bank whose every commit is
    /// Cicada's own maintenance (a fresh install that has run a state snapshot
    /// and nothing else) must not claim a model wrote it — that is a false
    /// provenance claim, the one thing this whole surface exists to prevent.
    ///
    /// Commits, not entities, because the sentence is about *authorship
    /// events*; the bar above it already carries the entity scale, and stating
    /// the same number twice in two units is the second-encoding G125 R1
    /// warns about.
    static func sentence(_ contributors: [Contributor]) -> String {
        guard !contributors.isEmpty else { return "Nothing attributed yet." }
        let commits = contributors.reduce(0) { $0 + $1.commitCount }
        let kinds = contributors.map(ContributorIdentity.kind(of:))
        let models = kinds.filter { $0 == "model" }.count

        var subjects: [String] = []
        if models > 0 {
            subjects.append("\(UsageFormat.count(models)) model\(models == 1 ? "" : "s")")
        }
        // Lowercase mid-sentence; the chip says `Copy.you` ("You") because it
        // starts its own line.
        if kinds.contains("user") { subjects.append("you") }
        if subjects.isEmpty {
            if kinds.contains("unknown") { subjects.append("authors from before provenance") }
            if kinds.contains("system") || subjects.isEmpty {
                subjects.append("Cicada's own maintenance")
            }
        }
        return "Across \(UsageFormat.count(commits)) commit\(commits == 1 ? "" : "s"), "
            + "\(list(subjects)) wrote this bank."
    }

    /// "a", "a and b", "a, b and c" — no Oxford comma, matching the rest of the
    /// app's prose.
    private static func list(_ parts: [String]) -> String {
        guard parts.count > 1 else { return parts.first ?? "" }
        return parts.dropLast().joined(separator: ", ") + " and " + (parts.last ?? "")
    }
}
