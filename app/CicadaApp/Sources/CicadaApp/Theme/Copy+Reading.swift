import Foundation

/// G166 — reading pages with the person's own agent: Settings → Agents → "Reading pages", the first-use sheet and the
/// Feed's Read section. Its own file for the reason `Copy+Lists.swift` gives. These are instructions and choices, never
/// promises: Cicada cannot enforce what an agent does in its own browser, so no line here says an agent never posts
/// or is read-only (TODO ruling 14, R-RW8). No price, no count of tokens (DR-59).
extension Copy {
    enum Reading {
        // MARK: Settings → Agents → Reading pages
        static let group = "Reading pages"
        static let switchTitle = "Let an agent read pages for you"
        static let switchDetail = "Some pages, LinkedIn and X among them, can only be read signed in, in your own browser, by an agent you run. You choose each page with “Ask an agent”. Cicada never signs in for you."
        static let switchLabel = "Let an agent read pages for you"
        static let hostSwitchDetail = "Cicada offers a page on this site to your agent only when you ask."
        static func hostSwitchLabel(_ site: String) -> String { "Allow \(site)" }
        static let loadFailed = "Couldn't read this setting just now. Open this page again to retry."
        static let saveFailed = "Couldn't save that. Try again."
        static func lastRead(_ day: String) -> String { "An agent has recorded a read · last \(day)" }
        static let copyPrompt = "Copy for an agent"
        static let copyPromptHelp = "The sentence to give your agent so it works through the pages you asked about"
        static let promptCopied = "Copied. Give it to your agent."

        // MARK: First-use sheet
        static let sheetTitle = "Let an agent read pages for you"
        static let sheetHow = "You choose each page with “Ask an agent”. Cicada then offers that page to your own agent, which can read it in your browser, signed in as you, and tell Cicada what it saw."
        static let sheetOnlyAsks = "Cicada only asks. What your agent does in your browser is up to it and you."
        static let sheetTerms = "Some sites, LinkedIn and X among them, forbid automated access even when you are signed in. You are responsible for following a site’s terms, and the site may restrict your account."
        static let sheetSaferExport = "If a site offers a download of your own data, that is safer."
        static let sheetSites = "Let an agent read pages from these sites (all off):"
        static let sheetUnderstand = "I understand"
        static let sheetNotNow = "Not now"
        static let sheetTurnOn = "Turn on"
        static let sheetTurnOnHelp = "Tick “I understand” first."

        // MARK: Feed → Read
        static let sectionLabel = "Read"
        static let anAgent = "an agent"
        static let cicadasReader = "Cicada’s reader"
        static let thisSite = "this site"
        static let notRead = "Not read by an agent"
        static let waiting = "Waiting for your agent"
        static func readBy(_ who: String) -> String { "Read by \(who)" }
        static func readBy(_ who: String, _ day: String) -> String { "Read by \(who) · \(day)" }
        static func needsLogin(_ host: String) -> String { "Needs you to sign in to \(host)" }
        static func blocked(_ host: String) -> String { "\(host) blocked the read" }
        static let notFound = "The page wasn’t found"
        static let failed = "The read failed"
        static func via(_ tool: String) -> String { "Read with: \(tool), as your agent reported" }
        static let ask = "Ask an agent"
        static let askAgain = "Ask again"
        static let openInBrowser = "Open in browser"
        static let openInBrowserHelp = "Open the link in your browser to sign in yourself, then ask again"
        static let askedNote = "Asked. Give your agent the sentence copied to your clipboard."
        static let askFailed = "Couldn't ask just now. Try again."
    }
}
