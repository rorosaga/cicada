import Foundation

/// G166 — reading pages with the person's own agent: Settings → Reading the web, the first-use sheet and the
/// Feed's Read section. Its own file for the reason `Copy+Lists.swift` gives. These are instructions and choices, never
/// promises: Cicada cannot enforce what an agent does in its own browser, so no line here says an agent never posts
/// or is read-only (TODO ruling 14, R-RW8). No price, no count of tokens (DR-59).
extension Copy {
    enum Reading {
        // MARK: Settings → Reading the web
        static let pageTitle = "Reading the web"
        static let pageSubtitle = "Which sites your own agent may read for you, and how it reads them."
        static let withAgentGroup = "With an agent"
        static let switchTitle = "Let an agent read pages for you"
        static let switchDetail = "When Cicada’s reader can’t open a page (a sign-in, a consent page, a refusal), your own agent can read it in your browser. You choose each page with “Ask an agent”, and which sites below. Cicada never signs in for you."
        static let switchLabel = "Let an agent read pages for you"
        static let loadFailed = "Couldn’t read this setting just now. Open this page again to retry."
        static let saveFailed = "Couldn’t save that. Try again."
        /// Critic L6(b): the sheet's wording changed since the person last ticked it, so the switch reads off until
        /// they read it again.
        static let reAskHelp = "The first-use sheet changed since you last agreed to it. The switch reads off until you read it and tick “I understand” again."
        static func lastRead(_ day: String) -> String { "An agent has recorded a read · last \(day)" }
        static let copyPrompt = "Copy for an agent"
        static let copyPromptHelp = "The sentence to give your agent so it works through the pages you asked about"
        static let promptCopied = "Copied. Give it to your agent."

        // MARK: How your agent reads
        static let methodsGroup = "How your agent reads"
        static let methodsDetail = "Cicada tells your agent which you chose. It can’t see or limit what your agent does in your browser."
        static let skillTag = "Skill"
        static let addToGraph = "Add to your graph"
        static let addToGraphHelp = "File this skill’s page in your graph, so an agent can find it there"
        static let openInGraph = "Open in graph"
        static let installSkill = "Install…"
        static let installSkillHelp = "See what it needs and how to set it up"
        static let skillInstalled = "Installed"
        static let skillNotInstalled = "Not installed yet"
        static let methodsFooter = "This applies to agents on this Mac that can load a skill. Apps you connect from anywhere use their own tools."
        static func methodRadioLabel(_ title: String) -> String { "Read with \(title)" }
        static func pageNote(_ state: String) -> String? {
            switch state {
            case "created", "adopted": return "Added this skill to your graph."
            case "busy": return "Sleep is updating your memory. Add it to your graph again in a moment."
            case "foreign": return "A page with that name is already in your graph, so Cicada left it alone."
            case "demo": return "This is the demo memory, so nothing is added to it."
            default: return nil
            }
        }

        // MARK: Sites that need your browser
        static let sitesGroup = "Sites that need your browser"
        static let sitesIntro = "A site is listed when Cicada’s own reader couldn’t open one of its saved pages. You decide which sites your agent may read. Turning one on queues its waiting pages for your agent, and pages saved later join by themselves."
        static let sitesEmpty = "No site needs your browser so far. One shows up here when Cicada’s reader can’t open a page you saved."
        static let sitesIconNote = "Site icons come from an icon service, which is told the site’s name. Cicada never contacts these sites itself."
        static func siteSwitchLabel(_ site: String) -> String { "Let an agent read \(site)" }
        static func waitingNotAllowed(_ n: Int) -> String { n == 1 ? "1 saved page is waiting" : "\(n) saved pages are waiting" }
        static func queued(_ n: Int) -> String { n == 1 ? "1 page is queued for your agent" : "\(n) pages are queued for your agent" }
        static let nothingWaiting = "Nothing is waiting"
        static func readCount(_ n: Int) -> String { n == 1 ? "1 read by an agent" : "\(n) read by an agent" }
        static let needsLoginNote = "Your agent wasn’t signed in to this site. Sign in in your browser, then try again."
        static let tryAgain = "Try again"
        static let tryAgainHelp = "Queue this site’s pages for your agent again"
        static func wallWords(_ wall: String?) -> String? {
            switch wall {
            case "walled": return "Cicada never asks this site for pages"
            case "login": return "Asks for a sign-in"
            case "consent": return "Shows a consent page"
            case "refused": return "Refused Cicada’s reader"
            default: return nil
            }
        }

        // MARK: First-use sheet
        static let sheetTitle = "Let an agent read pages for you"
        static let sheetHow = "You choose each page with “Ask an agent”, and which sites to allow. Cicada then offers those pages to your own agent, which can read them in your browser, signed in as you, and tell Cicada what it saw."
        static let sheetOnlyAsks = "Cicada only asks. What your agent does in your browser is up to it and you."
        static let sheetTerms = "Some sites, LinkedIn and X among them, forbid automated access even when you are signed in. You are responsible for following a site’s terms, and the site may restrict your account."
        static let sheetInstruction = "Cicada asks your agent not to type credentials, and not to post, message or change anything. It can’t see or enforce what happens in your browser."
        static let sheetSaferExport = "If a site offers a download of your own data, that is safer."
        static func sheetAlsoAllows(_ site: String) -> String { "This also lets an agent read pages from \(site)." }
        static let sheetUnderstand = "I understand"
        static let sheetNotNow = "Not now"
        static let sheetTurnOn = "Turn on"
        static let sheetTurnOnHelp = "Tick “I understand” first."

        // MARK: Home
        static let homeBlockTitle = "Needs your browser"
        static func homePagesNeedBrowser(_ n: Int) -> String {
            n == 1 ? "1 saved page needs your browser to be read" : "\(n) saved pages need your browser to be read"
        }
        static let homeOpenReading = "Reading the web"

        // MARK: Settings → Agents
        static let agentsRowTitle = "Reading pages"
        static let agentsRowDetail = "Which sites your agent may read for you in your browser, and how it reads them."

        // MARK: Feed → Read
        static let sectionLabel = "Read"
        static let anAgent = "an agent"
        static let cicadasReader = "Cicada’s reader"
        static let thisSite = "this site"
        static let notRead = "Not read by an agent"
        /// The wall Cicada's own reader hit on this page, in words (the site's own name never needed).
        static func wallLine(_ wall: String) -> String {
            switch wall {
            case "consent": return "Cicada’s reader couldn’t open this page: it stopped at a consent page."
            case "refused": return "Cicada’s reader couldn’t open this page: the site refused it."
            default: return "Cicada’s reader couldn’t open this page: it needs a signed-in browser."
            }
        }
        static func siteAllowedWaiting(_ site: String) -> String { "Waiting for your agent · \(site) is allowed" }
        static let allowSiteHelp = "Let your agent read this site’s saved pages in your browser"
        static func siteAllowedNote(_ site: String) -> String { "\(site) is allowed. Its saved pages are queued for your agent." }
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
        /// The Feed row's flag and the toast for a login wall an agent hit: ambient, so a person on another page
        /// or item still learns of it (the Read section on the link has the detail and the way out).
        static let rowFlag = "Needs sign-in"
        static func walledToast(_ hosts: [String]) -> String {
            hosts.count == 1 ? "\(hosts[0]) needs you to sign in. It's marked in the Feed."
                             : "\(hosts.count) pages need you to sign in. They're marked in the Feed."
        }
        /// The agent's own one-sentence note, marked as its words (never Cicada's).
        static func agentNote(_ who: String, _ note: String) -> String { "\(who) noted: \(note)" }
    }
}
