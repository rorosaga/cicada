import Foundation

/// G146 — the words pictures, Clusters' cards and the person card add, in their own file for the reason
/// `Copy+Inbox.swift` gives: parallel tracks edit `Copy.swift`. DR-59: sentence case, plain verbs, no ids (DR-54).
extension Copy {
    enum People {
        static let changePicture = "Change picture…"
        static let addPicture = "Add a picture…"
        static let change = "Change…"
        static let useInitials = "Use initials instead"
        static let removePicture = "Remove picture"
        static let pickPrompt = "Use picture"
        static let saveFailed = "Couldn't save the picture — try again."
        static let sleepBusy = "Sleep is updating your memory — try the picture again in a moment."
        static let backendDown = "Cicada's engine isn't running, so the picture wasn't saved."

        // Clusters (F-11, F-12)
        static let showAll = "Show all ›"
        static func showAllHelp(_ group: String) -> String { "Show every one of your \(group.lowercased())" }
        static let recencySuffix = "· recently mentioned first"

        // The person card (F-12)
        static let worksAt = "Works at"
        static let role = "Role"
        static let knownSince = "Known since"
        static let lastMentioned = "Last mentioned"
        static let conversations = "Conversations"
        static let contacts = "Contacts"
        static let matched = "Matched"
        static let photoMatched = "photo"
        static let dot = "·"
        static let showOnGraphHelp = "Show on the graph"
        static func firstIn(_ app: String) -> String { "first in \(app)" }
        static func pages(_ n: Int) -> String { n == 1 ? "1 page" : "\(UsageFormat.count(n)) pages" }
        static func openHelp(_ name: String) -> String { "Open \(name)" }

        // The person body (F-12)
        static let you = "you"
        static let cicada = "Cicada"
        static let sleep = "Sleep"
        static let writtenByPrefix = "Written by"
        static func writtenBy(_ who: String) -> String { "\(writtenByPrefix) \(who)" }
        static func believes(_ n: Int) -> String { "What Cicada believes · \(UsageFormat.count(n))" }
        static let newestFirst = "newest first"
        static func showMore(_ n: Int) -> String { "Show \(UsageFormat.count(n)) more" }
        static func firstName(_ name: String) -> String { name.split(separator: " ").first.map(String.init) ?? name }
        static func howYouKnow(_ name: String) -> String { "How you know \(firstName(name))" }
        static func connected(_ n: Int) -> String {
            n == 1 ? "Connected to 1 page in your memory." : "Connected to \(UsageFormat.count(n)) pages in your memory."
        }
        static let showOnGraph = "Show on the graph ›"
        static let whatsHappening = "What's happening"
        static func openProject(_ name: String) -> String { "Open \(name) ›" }
        static let ongoing = "Ongoing"
        static func since(_ day: String) -> String { "since \(day)" }
        static let showPage = "Show the page"
        static let hidePage = "Hide the page"

        /// How long someone has been in memory — a span in plain units, never a day word (those are `RelativeDay`'s).
        static func span(days: Int) -> String {
            func unit(_ n: Int, _ one: String, _ many: String) -> String {
                n == 1 ? "1 \(one)" : "\(UsageFormat.count(n)) \(many)"
            }
            if days < 14 { return unit(max(days, 0), "day", "days") }
            if days < 60 { return unit(days / 7, "week", "weeks") }
            if days < 365 { return unit(days / 30, "month", "months") }
            return unit(days / 365, "year", "years")
        }

        static func useDetected(_ source: PictureSource) -> String {
            switch source {
            case .contacts: "Use the photo from Contacts"
            case .logo: "Use the logo"
            case .thumbnail: "Use the saved preview"
            case .upload, .initials: "Use the picture Cicada found"
            }
        }

        static func optionLabel(_ option: PictureMenuModel.Option) -> String {
            switch option {
            case .change: changePicture
            case .add: addPicture
            case .useInitials: useInitials
            case .remove: removePicture
            case .useDetected(let source): useDetected(source)
            }
        }

        static func changeHelp(_ name: String) -> String { "Change the picture for \(name) — or drop one here" }
        static func pickMessage(_ name: String) -> String {
            "Choose a picture for \(name). Cicada keeps a small copy in your memory."
        }

        static func importFailed(_ failure: PictureImport.Failure) -> String {
            switch failure {
            case .unreadable: "That file isn't a picture Cicada can read."
            case .tooSmall: "That picture is too small to show."
            case .tooLarge: "That picture is still too large after shrinking it."
            }
        }

        /// C11 — where a picture came from: every picture's hover and the card's source line (F-12).
        static func sourceLine(_ source: PictureSource?) -> String {
            switch source {
            case .upload: "Picture you added"
            case .initials: "Initials — your choice"
            case .contacts: "Photo from your Contacts"
            case .logo: "Logo from its website"
            case .thumbnail: "Preview from the saved page"
            case nil: "No picture yet"
            }
        }
    }
}
