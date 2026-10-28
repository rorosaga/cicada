import Foundation

/// Projects v2 (TODO ruling 45) — the words for the person's own list, Suggested, the header, the "project knowledge"
/// panel and Add an influence. DR-59: sentence case, plain verbs, no "!"; provider-neutral (a provider is named only
/// where it is the person's own: their ChatGPT or Claude project). Q6: the dated list is called "Timeline".
extension Copy {
    enum ProjectsMine {
        // MARK: The list
        static let newProject = "New project"
        static let newProjectHelp = "Start a project of your own"
        static let nameField = "Name"
        static let namePlaceholder = "What it's called"
        static let descriptionField = "Description"
        static let descriptionPlaceholder = "One line on what it is, in your words"
        static let create = "Create"
        static let cancel = "Cancel"
        static let suggested = "Suggested"
        static let suggestedHelp = "Projects Cicada noticed that you haven't added. Nothing here is deleted."
        static let addToMine = "Add to my projects"
        static let notMine = "Not mine"
        static let notMineHelp = "Leave it out of your projects. It stays in memory, and you can add it later."
        static let nameItTitle = "Name this project"
        static let nameItMessage = "It's a group of your conversations with no name of its own."
        static let emptyMineTitle = "No projects of yours yet"
        static let emptyMineMessage = "Start one with New project, or add one Cicada suggests below."

        /// The reason a suggestion is offered, from the server's `whyKind` (its sentence rides as `why`).
        static func reasonGlyph(_ kind: String) -> String {
            switch kind {
            case "repo": return "chevron.left.forwardslash.chevron.right"
            case "words": return "text.quote"
            case "agent": return "sparkles"
            case "provider", "export": return "square.stack"
            case "fallback": return "circle.dashed"
            default: return "circle"
            }
        }

        /// A wire day (`YYYY-MM-DD`) as the reader's own words for it (DR-58: `RelativeDay`, never the raw ISO string).
        static func day(_ raw: String?, today: ISODay = ISODay.today(), locale: Locale = .autoupdatingCurrent) -> String? {
            guard let raw, let day = ISODay(String(raw.prefix(10))) else { return nil }
            return RelativeDay.absolute(day, today: today, locale: locale)
        }

        // MARK: The header
        static let editNameHelp = "Rename (Return to save, Esc to cancel)"
        static let editDescriptionHelp = "Edit the description (Return to save, Esc to cancel)"
        static let addDescription = "Add a description"
        static func startedLine(_ via: String?, day: String?) -> String {
            let how: String
            switch via {
            case "app", "cli": how = "You started this project"
            case "agent": how = "An agent started this on your ask"
            case "accepted": how = "You added this project"
            case "folder": how = "You named this folder as a project"
            case "import": how = "You made this project in Claude"
            case "progress": how = "You've logged progress here"
            default: how = "Suggested by Cicada"
            }
            return Self.day(day).map { "\(how) · \($0)" } ?? how
        }
        static func editedBy(_ by: String, day: String?) -> String {
            let who = by == "user" ? "you" : "\(OriginIconography.label(for: by)) on your ask"
            return "Description last edited by \(who)" + (Self.day(day).map { " · \($0)" } ?? "")
        }

        // MARK: Sections
        static let done = "Done"
        static let timeline = "Timeline"

        // MARK: The knowledge panel
        static func conversations(_ n: Int) -> String { "Conversations · \(UsageFormat.count(n))" }
        static let noConversations = "No conversation is tied to this project yet."
        static let notAboutThis = "Not about this project"
        static let tieHelp = "Cicada ties a conversation by its repository, your own words naming the project, what Sleep wrote about it, or your choice — never by a name that happens to come up."
        static func whyLine(_ counts: [String: Int]) -> String {
            let order: [(String, String)] = [("named", "you named it in"), ("repo", "in its repository"),
                                             ("claims", "Sleep tied"), ("added", "added by hand"),
                                             ("provider", "in your provider's project"), ("relay", "the app said")]
            return order.compactMap { key, words in
                guard let n = counts[key], n > 0 else { return nil }
                return "\(UsageFormat.count(n)) \(words)"
            }.joined(separator: " · ")
        }
        static func why(_ signal: String, provider: String?) -> String {
            switch signal {
            case "repo": return "In its repository"
            case "named": return "You named it"
            case "claims": return "Sleep tied it"
            case "added": return "Added by hand"
            case "provider": return "In your \(provider ?? "app") project"
            case "relay": return "The app said"
            default: return signal
            }
        }
        static func influences(_ n: Int) -> String { "Sources & influences · \(UsageFormat.count(n))" }
        static let noInfluences = "Nothing yet. Add a film, a paper, a tool or a person that fed it."
        static let addInfluence = "Add an influence"
        static func influenceBy(_ by: String, day: String?) -> String {
            let who: String
            switch by {
            case "user": who = "added by you"
            case "sleep": who = "from Sleep"
            default: who = "\(OriginIconography.label(for: by)) wrote"
            }
            return who + (Self.day(day).map { " · \($0)" } ?? "")
        }
        static let undo = "Undo"
        static let instructions = "Instructions"
        static let documents = "Documents"
        static func fromProvider(_ provider: String) -> String {
            "From your \(provider == "claude" ? "Claude" : provider == "chatgpt" ? "ChatGPT" : provider) project"
        }

        // MARK: Add an influence
        static let influenceTitle = "Add an influence"
        static let influencePlaceholder = "Paste a link, or name a film, book, tool, person…"
        static let alreadyInMemory = "Already in your memory"
        static func somethingNew(_ text: String) -> String { "Something new: “\(text)”" }
        static func aLink(_ text: String) -> String { "A link: \(text)" }
        static let howTitle = "How it fed the project"
        static let howInspired = "Inspired it"
        static let howReference = "A reference"
        static let howUses = "It uses it"
        static let howPerson = "A person on it"
        static let notePlaceholder = "In your words, optional"
        static let addInfluenceButton = "Add influence"
        static let back = "Back"
    }
}
