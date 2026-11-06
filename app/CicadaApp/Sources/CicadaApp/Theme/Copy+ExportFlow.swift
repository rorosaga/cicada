import Foundation

/// ROR-126 — asking the person's own agent to request a chat export, waiting for it with them, and choosing what
/// to bring in. Provider-neutral: a provider is named only on its own row, where it is the person's choice.
extension Copy {
    // MARK: Offer an agent the request

    /// One short line on why (the person said yes once per provider, in their own browser).
    static let exportAgentWhy = "A chat export catches your memory up on what you've already said. From then on Cicada reads as you go."
    static let exportAgentOfferTitle = "Have your agent request it"
    static func exportAgentAsk(_ vendor: String) -> String { "Request \(vendor) for me" }
    static let exportAgentAsked = "Asked. Tell your agent \"request my exports\"."
    static let exportAgentInBrowser = "In your own signed-in browser. You say yes to each one."
    static let exportAgentManual = "Your agent couldn't do this one. Open the page yourself."
    static func exportAgentRequested(_ vendor: String) -> String { "Your agent asked for the \(vendor) export" }

    // MARK: The worm waits

    static func exportWormLine(_ vendor: String, requested: String) -> String {
        "Waiting on your \(vendor) export · requested \(requested)"
    }

    static func exportWormWaiting(_ vendors: [String]) -> String {
        switch vendors.count {
        case 0: return ""
        case 1: return "Waiting on your \(vendors[0]) export"
        default: return "Waiting on your exports: \(vendors.joined(separator: ", "))"
        }
    }

    // MARK: Choose what to bring in

    static let exportChoiceLead = "Choose what to bring in"
    static let exportChoiceStart = "Start from"
    static let exportChoiceEverything = "Everything"
    static let exportChoicePickDate = "Pick a date"
    static let exportChoiceSelectAll = "Select all"
    static let exportChoiceSelectNone = "Select none"
    static let exportChoiceLeftOutBefore = "Left out of an earlier import"
    static func exportChoiceCount(_ chosen: Int, of total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(chosen, locale: locale)) of \(UsageFormat.count(total, locale: locale)) chats"
    }
    static let exportChoiceRemembered = "Chats you leave out are remembered, so a later export won't offer them as new."
    static let exportChoiceWelcomeButton = "Choose what to bring in"
}
