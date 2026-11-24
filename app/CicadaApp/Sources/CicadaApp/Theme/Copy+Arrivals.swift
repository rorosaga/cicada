import Foundation

// G245 (arrival join, owner 2026-11-24: "yes ofc join ... and let him say no") — the words of a first name Sleep joined to
// the person who newly appeared the same week. Said where the person looks: the connection's row and the page's History,
// each with "Not them". Provider-neutral: Cicada decided, never a model by name; a name is the person's own word.
extension Copy {
    enum Arrivals {
        /// On a connection's row, under its headline. `name` is the first-name page's own title.
        static func rowLine(_ name: String) -> String { "Joined to \(name): the same first name, new the same week" }
        static let notThem = "Not them"
        static let notThemHelp = "Take the name back off the page and never join the two again"
        static let undone = "Taken back"
        /// In the page's History, after who did it ("Cicada joined …").
        static func historyJoined(_ name: String?) -> String {
            guard let name, !name.isEmpty else { return "joined a name to this page: the same first name, new the same week" }
            return "joined \(name) to this page: the same first name, new the same week"
        }
    }
}
