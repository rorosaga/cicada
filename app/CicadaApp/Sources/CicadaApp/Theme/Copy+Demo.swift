import Foundation

/// G117 round 4 (T-Demo) and G152 — the demo's and the guided tour's words (DR-59: sentence case, plain verbs, no "!",
/// no prices, no ids). Their own file for the reason `Copy+Lists.swift` gives: parallel tracks edit `Copy.swift`.
extension Copy {
    enum Demo {
        // F-08's banner.
        static let bannerTitle = "You're exploring a demo"
        /// F-08 said "nothing you do here is kept"; the demo keeps its own edits until it is deleted, so the sentence
        /// says what is true instead: none of it reaches the person's own memory (capture is refused into it, R-CS10).
        static let bannerLine = "Made-up memories, with pictures and videos on every page. Nothing here is yours, "
            + "and nothing you do here reaches your own memory."
        static let restartTour = "Restart tour"
        static let restartTourHelp = "Walk through the pages again, from the search bar"
        static let finishSetup = "Finish setting up →"
        static let finishSetupHelp = "Leave the demo and set up your own memory"
        static let leaveFailed = "Couldn't leave the demo. Try again, or switch memory from the bar at the top."

        // Settings → General.
        static let settingsGroup = "Getting to know Cicada"
        static let demoTitle = "Demo memory"
        static let demoDetail = "Made-up memories with pictures and videos on every page, to try things safely. "
            + "Your own memory stays exactly as it is."
        static let demoActiveDetail = "You're in the demo now."
        static let exploreDemo = "Explore the demo"
        static let leaveDemo = "Back to your memory"
    }

    enum Tour {
        static func progress(_ n: Int, of total: Int) -> String {
            "\(UsageFormat.count(n)) of \(UsageFormat.count(total))"
        }
        static func accessibilityLabel(_ n: Int, of total: Int) -> String { "Tour, step \(progress(n, of: total))" }

        static let next = "Next"
        static let nextHelp = "Next stop (Return)"
        static let back = "Back"
        static let backHelp = "Previous stop (Left arrow)"
        static let done = "Done"
        static let doneHelp = "End the tour (Return)"
        static let skip = "Skip tour"
        static let skipHelp = "End the tour now (Esc)"

        static let searchTitle = "Search everything you've kept"
        static let searchBody = "Type a name, a project or half a sentence you remember. ⌘K opens this from any page, "
            + "and Ask answers with where each answer came from."
        static let homeTitle = "Today, at a glance"
        static let homeBody = "Home shows what came in today, what's still being set up, and anything that needs you."
        static let inboxTitle = "Questions only you can answer"
        static let inboxBody = "When Cicada isn't sure, it asks here. One tap answers, and you have a few seconds "
            + "to undo."
        static let inboxEmpty = "When Cicada isn't sure about something, it asks here. Nothing is waiting right now."
        static let personTitle = "Every belief says who wrote it"
        static let personBody = "Open anyone Cicada knows: each belief is signed by you, by Sleep, or by the agent "
            + "and model that wrote it, and one click shows the conversation it came from."
        static let personEmpty = "Once Cicada meets someone, their card lists what it believes about them, each "
            + "belief signed by who wrote it."
        static let projectsTitle = "Where each project stands"
        static let projectsBody = "Each project keeps its own story: a bar that fills up to today, what's in motion, "
            + "what's planned, and its backlog."
        static let projectsEmpty = "Mention a project to an agent or in a note and it gets a page here: where it "
            + "stands, what's planned and its backlog."
        static let sleepTitle = "Sleep turns the day into memory"
        static let sleepBody = "Cicada reads what came in and files it away, on its schedule or when you press "
            + "Consolidate. Nothing is read until one of those happens."

        // Home's offer (seam 3) and the replays.
        static let offerTitle = "Take a quick tour?"
        static let offerLine = "Six stops that show where everything lives. Skip any time."
        static let offerTake = "Take the tour"
        static let offerNotNow = "Not now"
        static let settingsTitle = "Guided tour"
        static let settingsDetail = "Six stops that show where everything lives. About a minute."
        static let helpRow = "Take the guided tour"
    }
}
