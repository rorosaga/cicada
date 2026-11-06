import Foundation

/// G205 / G61 — the Inbox's top cards: an agent asking, and the grouped Where-to-check review.
extension Copy {
    enum AgentRequests {
        static let signedIn = "I signed in"
        static let notNow = "Not now"
        static func title(site: String?) -> String { site.map { "Sign in to \($0)" } ?? "An agent needs you" }
        static func open(_ site: String) -> String { "Open \(site) in your browser" }
        static let askLine = "Get a notification when an agent asks?"
        static let notifyMe = "Notify me"
    }

    enum WhereToCheck {
        static let yes = "Yes"
        static let no = "No"
        // Inbox v2 (owner 2026-10-26: "I don't really get the confirmation of links"): what the card is, why each link
        // is there and what confirming it changes, said on the card rather than on hover.
        static let explainer = "Links Cicada found for your pages. Confirm the ones that are right: Cicada checks a confirmed link for updates, and agents look there first. Nothing is used until you confirm it."
        static let confirm = "Confirm"
        static let notTheirs = "Not theirs"
        static let notThis = "Not this one"
        static let fromYou = "You mentioned it in a conversation."
        static let fromAgent = "An agent found it in a conversation."
        static let fromAgentNoLine = "An agent suggested it."
        static let fromPage = "It's written on the page."
        static let fromSave = "It's a link you saved."
        /// A public listing named this as the page's official site; `doubt` is why Cicada did not trust it alone.
        static func fromListing(doubt: String?) -> String {
            let base = "A public listing gives it as the official site."
            switch doubt {
            case "homepage_unconfirmed", "content_unconfirmed": return base + " Its own homepage could not confirm the name."
            case "ambiguous": return base + " More than one thing shares the name."
            case "matched_by_alias": return base + " It matched an alias, not the name."
            case "country_conflict": return base + " The country does not match the page."
            case "record_names_another_site": return base + " Your conversations name a different site."
            default: return base
            }
        }
        static func effectPersonProfile(_ name: String, _ what: String) -> String {
            "Confirming makes it \(name)'s own \(what): their picture and updates can come from here."
        }
        static func effectPersonOther(_ name: String, _ what: String) -> String {
            "Confirming makes it \(name)'s \(what): Cicada checks it for updates."
        }
        static func effectWebsite(_ name: String) -> String {
            "Confirming makes it \(name)'s website: its logo and updates come from here."
        }
        static func effectRepo(_ name: String, _ what: String) -> String {
            "Confirming makes it \(name)'s \(what): Cicada checks it for updates."
        }
        static func effectOther(_ name: String, _ what: String) -> String {
            "Confirming makes this \(what) a place to check for \(name)."
        }
        static func showMore(_ n: Int) -> String { n == 1 ? "1 more page" : "\(UsageFormat.count(n)) more pages" }
        static let showMoreHelp = "Show the other pages' links"
        static func allPages(_ n: Int) -> String { "All \(UsageFormat.count(n)) pages" }
        static func rowHelp(yes: Bool, label: String) -> String {
            yes ? "Keep \(label) as a place to check" : "Not a place to check — never proposed again"
        }
        static let failed = "Couldn't save that answer"
    }
}
