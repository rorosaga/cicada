import Foundation

/// G218 — activity traces: the Sources row, its controls, the consent sheet, the permission helper, the timeline and
/// the menu bar. Plain words and provider-neutral (owner 2026-09-30): Sleep's engine is "the engine you chose", never
/// a name; Touch ID and System Settings are the Mac's own words.
extension Copy {
    enum Traces {
        // MARK: - The Sources row

        static let title = "Traces"
        static let turnOn = "Turn on"
        static let turnOnEllipsis = "Turn on…"
        static let whatTheyAre = "Traces keep a short, private timeline of what was in front of you on this Mac — the "
            + "app, the window, the page and when — so you can find \"the video I watched at 3:20\" later. They stay on "
            + "this Mac, encrypted, and are deleted on their own."

        // MARK: - The state line

        static let recording = "Recording on this Mac."
        static let pausedUntilResumed = "Paused until you resume."
        static func pausedUntil(_ when: String) -> String { "Paused until \(when)." }
        static let off = "Off."
        static let notThisMac = "This Mac only. Cicada here talks to a server, and traces stay on the Mac that records "
            + "them — turn them on in Cicada on that Mac."
        static func failed(_ why: String) -> String { "Traces couldn't be read: \(why)" }
        static let tryAgain = "Try again"

        // MARK: - Pause, forget, wipe

        static let pause = "Pause"
        static let pauseHelp = "Record nothing for a while. Nothing is captured while traces are paused."
        static let pauseHour = "For 1 hour"
        static let pauseTomorrow = "Until tomorrow"
        static let pauseResumed = "Until I resume"
        static let resume = "Resume"
        static let forget = "Forget the last 15 minutes"
        static let forgetHelp = "Delete everything recorded in the last 15 minutes, screenshots included."
        static let forgot = "The last 15 minutes are gone."
        static let wipe = "Wipe all traces…"
        static let wipeTitle = "Wipe all traces?"
        static let wipeConfirm = "Wipe all traces"
        static let wipeMessage = "This deletes every trace and screenshot, your traces settings and the key that locks "
            + "them, and turns traces off. What was already added to your memory — what you watched and read, and day "
            + "summaries — stays in your memory."
        static let wiped = "Every trace is gone, and traces are off."
        static let turnOff = "Turn off"
        static let turnOffHelp = "Stop recording. What was kept stays until it is deleted on its own, or until you wipe it."
        static let cancel = "Cancel"

        // MARK: - What is recorded

        static let recordSection = "What is recorded"
        static let screenshots = "Screenshots"
        static let screenshotsHelp = "A picture of your screens when what's in front changes, at most every five minutes, "
            + "and every fifteen while it doesn't. Its text is read on this Mac."
        static let titles = "Window titles"
        static let titlesHelp = "The title of the window in front. Never for chat and mail apps unless you allow them below."
        static let allowScreenRecording = "Allow screen recording…"
        static let allowAccessibility = "Allow window titles…"
        static let needsScreenRecording = "Screenshots need screen recording, which isn't allowed yet."
        static let needsAccessibility = "Window titles need Accessibility, which isn't allowed yet."

        // MARK: - Into memory

        static let memorySection = "Into memory"
        /// "Learn from my day" (owner 2026-10-28): one switch, off until the person turns it on.
        static let learn = "Learn from my day"
        static let learnHelp = "Once a day, Sleep reads a counted summary of yesterday: time on your projects, what you "
            + "read, which apps. Never the screenshots, the window titles or the timeline. Off until you turn it on. "
            + "Reading uses the engine you chose for Sleep, so your plan's usage or your key's spend."
        /// "What you watch and read" (2026-10-28): every site, not one (ruling 39b, generalised).
        static let watchAndRead = "What you watch and read"
        static let watchAndReadHelp = "Videos you watch join your watch history and pages you stay on join that day's "
            + "reading, on any site, from browsers you allow. Kept to look up later; nothing is read by a model."

        // MARK: - How long

        static let keepSection = "How long they're kept"
        static func timelineDays(_ n: Int) -> String { n == 1 ? "Timeline: 1 day" : "Timeline: \(n) days" }
        static func shotDays(_ n: Int) -> String { n == 1 ? "Screenshots: 1 day" : "Screenshots: \(n) days" }
        static let keepHelp = "You can keep them for less time, never longer."

        // MARK: - Left out

        static let excludeSection = "Never recorded"
        static let excludedApps = "Apps"
        static let excludedAppsNone = "No apps left out yet. Password managers and Cicada itself are never recorded."
        static let addApp = "Add an app"
        static let addAppHelp = "Pick an app that's open, or type its identifier."
        static let bundlePrompt = "com.example.App"
        static let add = "Add"
        static let remove = "Remove"
        static func removeHelp(_ name: String) -> String { "Stop leaving out \(name)" }
        static let excludedSites = "Sites"
        static let excludedSitesNone = "No sites left out yet."
        static let sitePrompt = "A site to leave out — your bank, a health site…"
        static let badBundle = "That isn't an app identifier — it looks like com.example.App."
        static let badSite = "That isn't a site name — it looks like bank.example."

        // MARK: - Browsers and titles per app

        static let browsersSection = "Addresses"
        static let browsersHelp = "Read the address of the page in front only from the browsers you allow. Never private "
            + "windows. macOS asks you once for each browser."
        static func browserNotAllowed(_ browser: String) -> String {
            "macOS hasn't allowed this yet. Open \(browser), then ask again."
        }
        static let askAgain = "Ask again"
        static let titleAppsSection = "Allow titles for…"
        static let titleAppsHelp = "Chat and mail apps keep only their name and times. Allow titles for one here."

        // MARK: - Status

        static let statusSection = "On this Mac"
        static func daysKept(_ n: Int) -> String { n == 1 ? "1 day kept" : "\(n) days kept" }
        static func sizeOnDisk(_ size: String) -> String { "\(size) on disk" }
        static func keyLives(_ where_: String) -> String { "The key: \(where_)." }
        static let browse = "Browse traces…"
        static let browseHelp = "See the timeline, search it, and see screenshots after Touch ID."

        // MARK: - The consent sheet

        static let consentTitle = "Turn on traces"
        static let whatTitle = "What is recorded"
        static let what = [
            "The app in front, and when.",
            "Window titles, once you allow Accessibility — never for chat and mail apps.",
            "The page's address, only from browsers you allow — never private windows.",
            "A screenshot of every screen you have connected when what's in front changes — at most every five minutes, "
                + "every fifteen while it doesn't — showing only apps whose windows may be kept. Its text is read on this Mac.",
            "Nothing while paused, while the screen is locked, while you type a password, or in apps and sites you leave out.",
        ]
        static let whereTitle = "Where it stays"
        static let where_ = "Only on this Mac, in Cicada's own folder, encrypted — outside your memory and its history. "
            + "Never sent anywhere, and never readable by your other devices or by remote agents."
        static let howLongTitle = "How long"
        static let howLong = "The timeline for 30 days; screenshots and their text for 7 days. Then they are deleted on "
            + "their own."
        static let intoMemoryTitle = "What joins your memory"
        static let intoMemory = "What you watch and read on any site joins your watch history and reading, to look up. "
            + "A daily summary Sleep learns from only if you turn it on."
        static let wipeTitleConsent = "How to wipe"
        static let wipeHow = "Wipe all traces deletes everything and its key. Pause any time from the menu bar."
        static let honestLimit = "Anything running as you on this Mac can read what you can — so traces are kept small, "
            + "short-lived and encrypted."
        static let notNow = "Not now"
        static let turnOnFailed = "Traces couldn't be turned on."

        // MARK: - Permission steps

        static let stepsTitle = "Two permissions, both optional"
        static let stepsLead = "Traces work with the app and times alone. Each permission adds one thing."
        static let stepTitles = "Window titles"
        static let stepTitlesLine = "Accessibility lets Cicada read the title of the window in front."
        static let stepShots = "Screenshots"
        static let stepShotsLine = "Screen recording lets Cicada take a picture of your screens."
        static let allow = "Allow…"
        static let allowed = "Allowed"
        static let skip = "Skip"
        static let done = "Done"

        // MARK: - The drag helper

        static func need(_ permission: TracePermission) -> String {
            switch permission {
            case .screenRecording: "I need screen recording. Drag me into the Screen Recording list."
            case .accessibility: "I need Accessibility. Drag me into the Accessibility list."
            case .fullDiskAccess: "I need Full Disk Access. Drag me into the Full Disk Access list."
            }
        }

        static func nearMiss(_ permission: TracePermission) -> String {
            switch permission {
            case .screenRecording: "Drag into 'Screen & System Audio Recording', not the audio-only list."
            case .accessibility: "Drag into the Accessibility list under Privacy & Security, then turn its switch on."
            case .fullDiskAccess: "Drag into 'Full Disk Access', then turn its switch on."
            }
        }

        static let open = "Open"
        static let openHelp = "Open this list in System Settings"
        static let dragHint = "Drag into the list"
        static let closeHelper = "Close"

        // MARK: - The timeline

        static let browserTitle = "Traces"
        static let searchPrompt = "Search traces"
        static let nothingThisDay = "Nothing was recorded this day."
        static let noDays = "Nothing recorded yet."
        static let noHits = "Nothing matches."
        static let loading = "Reading traces…"
        static let showScreenshots = "Show screenshots"
        static let showScreenshotsHelp = "Screenshots are shown only after Touch ID or your password."
        static let hideScreenshots = "Hide screenshots"
        static let authReason = "show your screenshots"
        static let authFailed = "Screenshots stay hidden."
        static func screenshotCount(_ n: Int) -> String { n == 1 ? "1 screenshot" : "\(n) screenshots" }
        static let screenshotsHiddenAgain = "Screenshots hide again after five minutes."
        static let readText = "Text on screen"
        static func unreadable(_ n: Int) -> String {
            n == 1 ? "1 record couldn't be read." : "\(n) records couldn't be read."
        }
        static let close = "Close"

        // MARK: - The Traces page (owner 2026-10-26)

        /// The page's one line on where traces live, with the person's own retention.
        static func staysHere(shotDays: Int, timelineDays: Int) -> String {
            let shots = shotDays == 1 ? "1 day" : "\(shotDays) days"
            let line = timelineDays == 1 ? "1 day" : "\(timelineDays) days"
            return "Everything here stays on this Mac, encrypted; screenshots \(shots), timeline \(line)."
        }
        static let settings = "Settings…"
        static let settingsHelp = "Pause, what is recorded, how long it is kept, what is never recorded."
        static let settingsTitle = "Traces settings"
        static let daysSection = "Days"
        /// Sources' Traces row once the page exists: one line and the way there.
        static let onItsPage = "Your traces have their own page: your days, what joins memory, and screenshots after "
            + "Touch ID."
        static let openPage = "Open Traces"
        static let openPageHelp = "Go to the Traces page."

        // MARK: - The Traces page, redesigned (owner 2026-10-28)

        static let allScreensOffer = "Screenshots can now cover every screen you have connected."
        /// Once, for someone upgraded with the YouTube switch on (2026-10-28).
        static let readingNotice = "This used to be YouTube only. It now keeps the pages you stay on and the videos "
            + "you watch on any site, from browsers you allow — still only to look up, never read by a model. The switch "
            + "is right above if you'd rather not."
        static let gotIt = "Got it"
        static let review = "Review…"
        static let previewSection = "Yesterday, as Sleep would read it"
        static func previewSectionFor(_ day: String) -> String { "\(day), as Sleep would read it" }
        static let previewTrailing = "Counted on this Mac · nothing sent"
        static let previewFoot = "Time is matched to a project only through its folders, its repository or an address "
            + "tied to it. Anything else stays in \"Everything else\"."
        static let yourProjects = "Your projects"
        static let reading = "Reading"
        static let watching = "Watching"
        static let calls = "Calls"
        static let everythingElse = "Everything else"
        static func pagesOnSites(_ pages: Int, _ sites: Int) -> String {
            "\(pages == 1 ? "1 page" : "\(pages) pages") on \(sites == 1 ? "1 site" : "\(sites) sites")"
        }
        static func videos(_ n: Int) -> String { n == 1 ? "1 video" : "\(n) videos" }
        static func callCount(_ n: Int) -> String { n == 1 ? "1 call" : "\(n) calls" }
        static func switchesAtBusiest(_ n: Int) -> String { "switched apps \(n) times in the busiest hour" }
        static let addedSection = "What traces added"
        static func added(beliefs: Int, progress: Int, since: String?) -> String {
            var parts: [String] = []
            if beliefs > 0 { parts.append(beliefs == 1 ? "1 belief" : "\(beliefs) beliefs") }
            if progress > 0 { parts.append(progress == 1 ? "1 progress note" : "\(progress) progress notes") }
            let what = parts.joined(separator: " and ")
            return since.map { "\(what), since \($0)" } ?? what
        }
        static let addedLine = "Each says it came from your day's summary, and none of them counts as a mention."
        static let show = "Show"
        static let hide = "Hide"
        static func allCount(_ n: Int) -> String { "All \(n)" }
        static let removeFromMemory = "Remove from memory…"
        static let removeTitle = "Remove what traces added?"
        static let removeConfirm = "Remove from memory"
        static let removeMessage = "Every belief and progress note that only your day's summaries support is closed, in "
            + "one change you can undo. Beliefs another conversation also supports stay."
        static func removed(_ n: Int) -> String { n == 1 ? "Removed 1 from memory." : "Removed \(n) from memory." }
        static let undo = "Undo"
        static func restored(_ n: Int) -> String { n == 1 ? "Put 1 back." : "Put \(n) back." }
        static let nothingToRemove = "Nothing traces added is left to remove."
        // Days
        static let allDays = "All days"
        static let allDaysHelp = "Back to every day"
        static func screensConnected(_ n: Int) -> String { "\(n) screens connected" }
        static func screenOf(_ i: Int, _ n: Int) -> String { "Screen \(i) of \(n)" }
        static func dayLine(seconds: Int, apps: Int) -> String {
            let a = apps == 1 ? "1 app" : "\(apps) apps"
            return seconds > 0 ? "\(duration(seconds)) · \(a)" : a
        }
        static func duration(_ seconds: Int) -> String {
            let m = Int((Double(seconds) / 60).rounded())
            if m < 1 { return "under a minute" }
            if m < 60 { return "\(m) m" }
            return m % 60 == 0 ? "\(m / 60) h" : "\(m / 60) h \(m % 60) m"
        }
        static let lockedCover = "Shown after Touch ID"
        static let deleteDay = "Delete day…"
        static func deleteDayTitle(_ day: String) -> String { "Delete everything from \(day)?" }
        static let deleteDayConfirm = "Delete day"
        static let deleteDayMessage = "Every span and screenshot of this day goes from this Mac. What already joined your "
            + "memory stays; Remove from memory is for that."
        static let deleteItem = "Delete"
        static func deleteHelp(_ what: String) -> String { "Delete \(what) from this day" }
        static let deleteSpanHelp = "Delete this moment and the screenshots taken of it"
        static let appsSection = "Apps"
        static let sitesSection = "Sites"
        static let timelineSection = "Timeline"
        static let screenshotSection = "Screenshots"

        // MARK: - The menu bar

        static let menuRecording = "Recording traces"
        static let menuPaused = "Traces paused"
        static func menuPausedUntil(_ when: String) -> String { "Traces paused until \(when)" }
        static let menuPausedUntilResumed = "Traces paused until you resume"
        static let menuPause = "Pause traces"
        static let menuResume = "Resume traces"
        static let menuForget = "Forget the last 15 minutes"
    }
}
