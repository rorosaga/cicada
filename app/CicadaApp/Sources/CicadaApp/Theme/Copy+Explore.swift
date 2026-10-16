import Foundation

/// G166 exploring (owner 2026-10-14) — the Explore sheet on Sources, the run card and the Settings switch. Provider-
/// neutral (owner 2026-09-30): the person's own agent does the visiting, and no line names a provider or promises what
/// an agent will do in a browser Cicada cannot see. A size and minutes, never a price (ruling 12).
extension Copy {
    enum Explore {
        // MARK: Sources
        static let button = "Explore saved sites"
        static let buttonHelp = "Have your own agent visit your saved sites and keep a dated picture of how each looks."
        static let sheetTitle = "Explore your saved sites"
        static let sheetIntro = "Your own agent visits each site in your browser, one at a time, and Cicada keeps a dated picture of how it looked, what it is made of and what it says it is. Cicada never opens a browser itself."
        static let scopeNever = "Sites not explored yet"
        static let scopeAll = "Every saved site"
        static let browsersLabel = "From"
        static let start = "Explore"
        static let startHelpOff = "Turn on “Let an agent read pages for you” in Settings, Reading the web, first."
        static let startHelpNone = "No saved site to explore."
        static let startHelpDemo = "The demo memory holds made-up sites; exploring works in your own memory."
        static let startHelpSkill = "This copy of Cicada’s capture script doesn’t match the reviewed one. Update Cicada first."
        static let signedInNote = "Your agent uses your signed-in browser session, so a site sees you as you. You can turn that off in Settings, Reading the web."
        static let privateNote = "Your agent uses a private browser context with no cookies, so no site sees your accounts."
        static let copyPrompt = "Copy for an agent"
        static let copied = "Copied. Paste it into your agent."
        static let notNow = "Close"
        static func count(_ n: Int) -> String { n == 1 ? "1 site" : "\(UsageFormat.count(n)) sites" }
        static func size(_ estimate: ExploreEstimate) -> String {
            let word = ["light": "Light", "medium": "Medium", "heavy": "Heavy"][estimate.size] ?? "Light"
            return estimate.minutes > 0 ? "\(word) · about \(estimate.minutes) min with four agents" : word
        }
        static func leftOut(_ excluded: [String: Int]) -> String? {
            let total = excluded.filter { $0.key != "hidden" }.values.reduce(0, +)
            guard total > 0 else { return nil }
            return "\(UsageFormat.count(total)) left out: private documents, videos, papers, sites that need your sign-in, and any you set to Never explore."
        }

        // MARK: The run card
        static let cardTitle = "Exploring your saved sites"
        static let stop = "Stop"
        static let stopHelp = "Sites still waiting are dropped; a site an agent is visiting finishes."
        static let addAgentHelp = "Copy the prompt again, to hand the run to another agent."
        static let finished = "Done exploring"
        static let stopped = "Stopped"
        static let readingLink = "Reading the web"

        /// "Exploring 212 of 534 · 4 agents working · 3 need your sign-in · 2 gone · about 40 min left".
        static func progress(_ b: ExploreBatch) -> String {
            var parts = ["\(b.isRunning ? "Exploring" : b.stoppedAt != nil ? "Stopped at" : "Explored") \(UsageFormat.count(b.done)) of \(UsageFormat.count(b.total))"]
            if b.isRunning {
                parts.append(b.agents == 0 ? "waiting for an agent" : b.agents == 1 ? "1 agent working" : "\(b.agents) agents working")
            }
            if b.needsLogin > 0 { parts.append(b.needsLogin == 1 ? "1 needs your sign-in" : "\(b.needsLogin) need your sign-in") }
            if b.blocked > 0 { parts.append("\(b.blocked) blocked") }
            if b.gone > 0 { parts.append("\(b.gone) gone") }
            if b.failed > 0 { parts.append("\(b.failed) couldn’t be done") }
            if b.isRunning, let eta = b.etaMinutes { parts.append(eta <= 1 ? "about a minute left" : "about \(eta) min left") }
            return parts.joined(separator: " · ")
        }

        /// Who started it: the person's click says nothing; an agent's start names it (D5).
        static func startedBy(_ s: ExploreStarter) -> String? {
            guard s.isAgent else { return nil }
            return "Started by \(s.harness.map { ReadWords.harnessName($0) } ?? "an agent") at your request"
        }

        static func loadFailed(_ error: any Error) -> String {
            if let api = error as? APIError, case .serverUnreachable = api {
                return "Cicada's backend isn't answering. It restarts on its own — try again in a moment."
            }
            return "Something went wrong reading the explore run. Try again in a moment."
        }
        static let saveFailed = "Couldn’t do that just now. Try again."

        // MARK: Settings → Reading the web
        static let signedInTitle = "Explore in your signed-in browser"
        static let signedInDetail = "When your agent explores your saved sites it uses your everyday browser session, so a site shows what it shows you. Turn this off to explore in a private context with no cookies instead."
        static let signedInLabel = "Explore in your signed-in browser"
        static let neverGroup = "Never explore"
        static let neverTitle = "Sites never to explore"
        static let neverDetail = "Your agent is never handed these sites to explore, on this Mac, in every memory."
        static let neverPlaceholder = "bob-example.org"
        static let neverAdd = "Add"
        static let neverAddHelp = "Never explore this site."
        static let neverRemove = "Remove"
        static let neverRemoveHelp = "Let your agent explore this site again."
    }
}
