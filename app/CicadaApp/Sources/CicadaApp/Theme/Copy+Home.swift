import Foundation

/// Home: the front door gets out of the way (owner ruling 2026-10-14, "Graduate + Needs you first"). Home's own copy
/// file, for Track I's R-IA19 reason: a parallel track appends elsewhere, and one file per track means no two of them
/// edit the same lines. Plain words, no internal vocabulary (DR-59), and a vendor's name only on that vendor's own
/// export row (provider-neutral copy). `homeFrontDoorLabels` and `homeFrontDoorSentences` feed `HomeFrontDoorTests`.
extension Copy {
    // MARK: Getting started, graduated (review #2)
    static func homeSetupLine(left: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Setup · \(UsageFormat.count(left, locale: locale)) \(left == 1 ? "thing" : "things") left"
    }
    static let homeSetupShow = "Show ›"
    static let homeSetupShowHelp = "Show what is left of setup"
    static let homeSetupShowLess = "Show less"

    // MARK: Getting started's groups (review #7)
    static let gsConnected = "Connected"
    static let gsPastChats = "Your past chats"
    static let gsFirstRead = "First read"
    /// The refused commands sit behind this (DR-39); the sentence above them leads with the fix.
    static let gsShowCommands = "Show the commands"
    static let gsHideCommands = "Hide the commands"

    // MARK: An export row (review #1, #11)
    static func homeSeeHowHelp(_ vendor: String) -> String { "See how to get your \(vendor) export" }
    /// The wait line leads with what to look for (`reminderTitle`'s sentence, shortened to a line).
    static func homeWaitLine(_ vendor: String, requested: String) -> String {
        "Check your email for the \(vendor) link · requested \(requested)"
    }

    // MARK: Home's blocks (review #5, #8, #9)
    static let homeOpenSleepHelp = "Open the Sleep page"
    static let homeLastReadHelp = "See this read on the Sleep page"
    static let homeNothingYetTitle = "Nothing here yet"
    static let homeNothingYetLine = "Chat with a connected app, or drop an export. What Cicada learns shows up here."
    /// An empty block is its label and a short note — no card (DR-37).
    static func homeEmptyLabel(_ title: String, note: String) -> String { "\(title) · \(note)" }
    static let homeTodayNothingYet = "nothing yet"
    static let homeNeedsYouNothing = "nothing right now"
    static let homeLastReadNotYet = "not yet"

    static let homeFrontDoorLabels: [String] = [
        homeSetupLine(left: 1), homeSetupLine(left: 2), homeSetupShow, homeSetupShowHelp, homeSetupShowLess,
        gsConnected, gsPastChats, gsFirstRead, gsShowCommands, gsHideCommands,
        homeSeeHowHelp("ChatGPT"), homeOpenSleepHelp, homeLastReadHelp, homeNothingYetTitle,
        homeEmptyLabel(homeNeedsYou, note: homeNeedsYouNothing), homeEmptyLabel(homeToday, note: homeTodayNothingYet),
        homeEmptyLabel(homeLastRead, note: homeLastReadNotYet),
    ]
    static let homeFrontDoorSentences: [String] = [homeNothingYetLine,
                                                   homeWaitLine("ChatGPT", requested: "2 hours ago")]
}
