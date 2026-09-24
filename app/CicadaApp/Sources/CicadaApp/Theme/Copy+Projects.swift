import Foundation

/// G141 PJ-5 — the Projects page's words (DR-59: sentence case, plain verbs, no "!", no bare "%", no ids — DR-54; no
/// prices). Its own file for the reason `Copy+Lists.swift` gives: parallel tracks edit `Copy.swift`. Day words are NOT
/// here — `RelativeDay` spells them, once (DR-58). And nothing here says "Timeline": that is the entity card's tab for
/// contested beliefs, and the card can share the screen with the band (R-PP12, R-PJ22).
extension Copy {
    enum Projects {
        // MARK: The page
        static let page = "Projects"
        static let active = "Active"
        static let quiet = "Quiet"
        static let tabMenu = "Show"
        static let gathering = "Gathering your projects…"
        static let reading = "Reading this project…"
        static let readingCard = "Reading this page…"
        static let loadFailedTitle = "Couldn't load your projects"
        static let projectFailedTitle = "Couldn't open this project"
        static let emptyTitle = "No projects yet"
        static let emptyMessage = "Projects appear once Cicada has heard about one in two conversations."
        static let noneActive = "Nothing is in motion right now."
        static let noneQuiet = "Nothing has gone quiet."
        static let gone = "This project isn't in this bank any more."
        static let find = "Find a project…"
        static let stillIndexing = "still indexing"
        static let stillIndexingHelp = "Cicada is still building its search index, so a few links may be missing for a moment."
        static let planned = "Planned"
        static let noPlanYet = "No plan yet"
        static let closeHelp = "Close (Esc)"
        static let openHelp = "Open this project"
        static let tag = "Project"
        static let moreHelp = "More for this project"
        static let openCard = "Open its card"
        static func projectsBack(_ n: Int) -> String { n == 1 ? "‹ 1 project" : "‹ \(UsageFormat.count(n)) projects" }
        static func partOf(_ name: String) -> String { "Part of \(name) ›" }
        static func loadFailed(_ error: any Error) -> String {
            if let api = error as? APIError, case .serverUnreachable = api {
                return "Cicada's backend isn't answering. It restarts on its own — try again in a moment."
            }
            return "Something went wrong reading your projects. Try again in a moment."
        }
        static func countActive(_ n: Int) -> String { "\(UsageFormat.count(n)) active" }
        static func countQuiet(_ n: Int) -> String { "\(UsageFormat.count(n)) quiet" }
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static func noMatch(_ query: String) -> String { "No project matches “\(query)”" }

        // MARK: A row (R-PP7)
        static func quietThread(days: Int, text: String) -> String { "Quiet \(UsageFormat.count(days)) days · \(text)" }
        static func quietFor(days: Int) -> String { "Quiet \(UsageFormat.count(days)) days" }
        static func resting(lastHeard day: String) -> String { "Resting · last heard \(day)" }
        static let nothingHeard = "Nothing heard yet"
        static func lastHeard(_ day: String) -> String { "Last heard \(day)" }
        static func next(_ name: String, _ when: String?) -> String { when.map { "Next · \(name), \($0)" } ?? "Next · \(name)" }
        static func nextOverdue(_ name: String, since day: String) -> String { "Next · \(name), overdue since \(day)" }
        static func doneOf(_ p: ProjectProgress) -> String {
            "\(UsageFormat.count(p.done)) of \(UsageFormat.count(p.total)) done"
        }
        static func milestonesDone(_ p: ProjectProgress) -> String {
            "\(UsageFormat.count(p.done)) of \(UsageFormat.count(p.total)) milestones done"
        }
        static func shortPlanned(_ p: ProjectProgress, next: String?) -> String {
            next.map { "\(doneOf(p)) · \($0)" } ?? doneOf(p)
        }
        static func noPlanLast(_ day: String?) -> String { day.map { "No plan yet · last \($0)" } ?? noPlanYet }
        static func nextShort(_ name: String, _ day: String?) -> String { day.map { "\(name) \($0)" } ?? name }
        static func questions(_ n: Int) -> String { n == 1 ? "1 question" : "\(UsageFormat.count(n)) questions" }
        static func lastActivity(_ day: String) -> String { "Last activity \(day)" }
        static let noActivity = "No activity yet"
        static func people(_ names: [String]) -> String { "With \(names.joined(separator: ", "))" }
        static func barHelp(planned: Bool, progress: ProjectProgress) -> String {
            planned ? "\(milestonesDone(progress)); the green runs to today"
                : "No plan yet; the green runs from the first moment to today, and the end stays open"
        }
        static func rowLabel(_ name: String, planned: Bool, progress: ProjectProgress) -> String {
            "\(name) — \(planned ? milestonesDone(progress) : "no plan yet")"
        }

        // MARK: The band (R-PP10, R-PP12)
        static func since(_ day: String) -> String { "Since \(day)" }
        static let youToday = "You, today"
        static func bandLabel(_ name: String, planned: Bool, progress: ProjectProgress, today: String) -> String {
            "Progress of \(name), \(planned ? milestonesDone(progress) : "no plan yet"). You are here, today, \(today)."
        }
        static func happened(_ words: String, _ when: String) -> String { "Happened: \(words), \(when)" }
        static func saidHere(_ words: String, _ when: String) -> String { "Said here: \(words), \(when)" }
        static func fromHistory(_ words: String, _ when: String) -> String { "From the page's history: \(words), \(when)" }
        static func milestoneMark(_ name: String, _ words: String) -> String { "Milestone \(name), \(words)" }
        static func milestoneDoneOn(_ day: String) -> String { "done \(day)" }
        static func milestoneUpcoming(_ day: String, _ distance: String) -> String { "\(day) · \(distance)" }
        static func milestoneOverdue(_ day: String) -> String { "\(day) · overdue" }
        static func milestonePassed(_ day: String) -> String { "\(day) · passed, no word" }
        static func milestoneMissed(_ day: String) -> String { "\(day) · missed" }
        static func earlierTarget(_ name: String) -> String { "\(name) — its earlier date" }
        static func movedOn(_ from: String, _ on: String) -> String { on.isEmpty ? from : "\(from), moved \(on)" }
        static func nextMark(_ name: String, _ distance: String) -> String { "\(name) · \(distance)" }
        static func earlier(_ n: Int) -> String { n == 1 ? "1 earlier" : "\(UsageFormat.count(n)) earlier" }
        static func moreHere(_ n: Int) -> String { "+\(UsageFormat.count(n)) more here" }
        static func inMotion(_ text: String, _ when: String) -> String { "In motion: \(text), \(when)" }
        static func sinceDay(_ day: String) -> String { "since \(day)" }
        static func quietDays(_ n: Int) -> String { "quiet \(UsageFormat.count(n)) days" }
        static let startedToday = "started today"
        static func ongoingUntil(_ day: String) -> String { "ongoing until \(day)" }

        // MARK: The sections (R-PP13…R-PP18)
        static let now = "Now"
        static let lately = "Lately"
        static let plan = "Plan"
        static let around = "Around this project"
        static let collapse = "Collapse"
        static let expand = "Expand"
        static func inMotionCount(_ n: Int) -> String { "\(UsageFormat.count(n)) in motion" }
        static func happeningsCount(_ n: Int) -> String { n == 1 ? "1 happening" : "\(UsageFormat.count(n)) happenings" }
        static func nothingInMotion(lastHeard day: String?, distance: String?) -> String {
            guard let day, let distance else { return "Nothing in motion right now" }
            return "Nothing in motion right now · last heard \(day) (\(distance))"
        }
        static func waiting(_ n: Int, newest: String?) -> String {
            let count = n == 1 ? "1 conversation is" : "\(UsageFormat.count(n)) conversations are"
            return newest.map { "\(count) waiting for Sleep — the newest from \($0)" } ?? "\(count) waiting for Sleep"
        }
        static let waitingHelp = "Cicada reads these the next time it sleeps; until then they aren't in this project's story."
        static func threadSince(_ day: String) -> String { "Since \(day)" }
        static func threadQuiet(since day: String, days: Int) -> String { "Since \(day) · quiet \(UsageFormat.count(days)) days" }
        static let threadStartedToday = "Started today"
        static func threadHeard(since day: String, heard: String) -> String { "Since \(day) · last heard \(heard)" }
        static let howDidItGo = "How did it go? ›"
        static let howDidItGoHelp = "Answer this follow-up in the Inbox"
        static let statusDone = "Done"
        static let statusOngoing = "Ongoing"
        static let statusSaid = "Said here"
        static let statusChanged = "Changed"
        static let statusEnded = "Ended"
        static let statusStopped = "Stopped"
        static let statusHistory = "From the page's history"
        static func statusQuiet(_ n: Int) -> String { "Quiet \(UsageFormat.count(n)) days" }
        static func statusOngoingUntil(_ day: String) -> String { "Ongoing until \(day)" }
        static func moreFacts(_ n: Int) -> String { "+\(UsageFormat.count(n)) \(n == 1 ? "fact" : "facts")" }
        static func via(_ name: String) -> String { "via \(name)" }
        static func onProject(_ name: String) -> String { "on \(name)" }
        static let showInConversation = "Show in conversation ›"
        static let hideConversation = "Hide conversation"
        static let showHelp = "Open the words this came from beside the project"
        static let yourNote = "Your note in Cicada"
        static let setByYou = "Set by you in Cicada"
        static let pageHistory = "From the page's history — no source sentence"
        static let noSource = "[ no source recorded ]"
        static let you = "you"
        static func youHelp(_ name: String) -> String { "\(name) — you" }
        static func openEntity(_ name: String, type: String) -> String { "Open \(name), \(type.lowercased())" }
        static func openLink(_ host: String) -> String { host.isEmpty ? "Open the link" : "Open \(host)" }
        static let resume = "Resume"
        static func resumeHelp(_ app: String) -> String { "Resume this conversation in \(app)" }
        static func startedTracking(_ day: String) -> String { "Cicada started tracking this · \(day)" }
        static let basisStated = "Dated from your words"
        static let basisTurn = "Dated by when it was said"
        static let basisEpisode = "Dated by the conversation's day"
        static let basisPerson = "Set by you"
        static let basisWritten = "Dated when it was recorded"
        static let basisDay = "Dated by the day it was noted"
        static func doneOn(_ day: String) -> String { "Done \(day)" }
        static func early(_ n: Int) -> String { "\(UsageFormat.count(n)) \(n == 1 ? "day" : "days") early" }
        static func late(_ n: Int) -> String { "\(UsageFormat.count(n)) \(n == 1 ? "day" : "days") late" }
        static let onItsDate = "on its date"
        static func upcoming(_ day: String, _ distance: String) -> String { "\(day) · \(distance)" }
        static func overdueSince(_ day: String) -> String { "Overdue since \(day)" }
        static let someday = "Someday · no date yet"
        static func passedNoWord(_ day: String) -> String { "\(day) · passed, no word on how it went" }
        static func missed(_ day: String?) -> String { day.map { "Missed · \($0)" } ?? "Missed" }
        static let dropped = "Dropped"
        static func moved(_ n: Int) -> String { n == 1 ? "moved once" : "moved \(UsageFormat.count(n)) times" }
        static func plannedOn(target: String, on: String) -> String { "\(target) — planned \(on)" }
        static func movedByYou(target: String, on: String) -> String { "\(target) — moved by you on \(on)" }
        static func movedOnDay(target: String, on: String) -> String { "\(target) — moved on \(on)" }
        static let noPlan = "No plan yet. Nothing here is late or missing — it just hasn't been dated."
        static let documentsAndLinks = "Documents & links"
        static let partsOfThisProject = "Parts of this project"
        static let notAPageYet = "mentioned once, not a page yet"
        static let notAPageYetHelp = "Mentioned once — it becomes a page when it comes up in a second conversation"
        static func lastSeen(_ day: String) -> String { "last \(day)" }
        static func lastMentioned(_ day: String) -> String { "Last mentioned \(day)" }
        static func moreMembers(_ n: Int) -> String { "+\(UsageFormat.count(n)) more" }
        static func alsoUses(_ names: [String]) -> String { "Also uses: \(names.joined(separator: " · "))" }
        static func showSpecs(_ name: String) -> String { "Show what Cicada knows about \(name)" }
        static func hideSpecs(_ name: String) -> String { "Hide what Cicada knows about \(name)" }
        static let noSpecs = "Nothing recorded about it yet."
        static let aroundIndexing = "Still indexing — more may appear here in a moment."
        static let openProject = "Open project ›"

        // MARK: Writes (R-PP19…R-PP22, R-PP25)
        static let logPlaceholder = "Log progress — “Yesterday I got …”"
        static func logLabel(_ name: String) -> String { "Log progress on \(name)" }
        static let logButton = "Log"
        static let logHint = "⏎ saves it as done · ⌘⏎ as still going · the day comes from your words, or the date chip"
        static let saving = "Saving…"
        static func logged(_ name: String, day: String, how: String) -> String { "Logged on \(name) for \(day) — \(how)" }
        /// The server folded the note into a line already on the page (rule 2): nothing new to take back.
        static func alreadyNoted(_ name: String) -> String { "Already on \(name) — noted" }
        static let fromYourWords = "dated from your words"
        static let fromTheChip = "the day you picked"
        static let noDayInWords = "no day in your words, so today"
        static func dayAndDistance(_ day: String, _ distance: String) -> String { "\(day) (\(distance))" }
        static let dateChipHelp = "Pick the day this happened, when your words don't say it"
        static let undo = "Undo"
        static let undoHelp = "Take this back"
        static let done = "Done"
        static let stillGoing = "Still going"
        static let stopped = "Stopped"
        static let doneHelp = "Mark it done, dated today (D)"
        static let stillGoingHelp = "Still going as of today"
        static let stoppedHelp = "It stopped without finishing — dated today"
        static let markDone = "Mark done"
        static let rename = "Rename"
        static let renameHelp = "Change what this milestone is called"
        static let save = "Save"
        static let cancel = "Cancel"
        static let addMilestone = "Add a milestone"
        static let addMilestoneHelp = "Add a milestone (M)"
        static let milestoneName = "What's the milestone?"
        static let milestonePlaceholder = "A milestone — “Demo dry run”"
        static let addDate = "Add a date"
        static let removeDate = "No date"
        static let add = "Add"
        static let notRight = "Not right"
        static let notRightHelp = "Cicada misheard — take this back"
        static let sleepBusy = "Sleep is writing this project, try again in a moment"
        static let sleepRunningHelp = "Sleep is writing your memory — this can be saved once it finishes"
        static let saveFailed = "Couldn't save that — nothing changed"
        static let notOnProject = "That's no longer on this project — showing what's there now"
        static let backendDown = "Cicada's backend isn't answering — nothing changed"
        static let noPlanAdd = "No plan yet —"
    }
}

extension Copy.Projects {
    /// G150 — the Backlog section and its item card. For a person (DR-59): no ids but an item's own address (R-B24),
    /// no prices ("Paid AI" says what a task needs, never what it costs), no day words — `RelativeDay` spells those
    /// (DR-58) — and never "Timeline" (R-PP12).
    enum Backlog {
        static let title = "Backlog"
        static let tabMenu = "Backlog"
        static let open = "Open"
        static let doing = "Doing"
        static let done = "Done"
        static let dropped = "Dropped"
        static let all = "All"
        static let apply = "Apply"
        static let research = "Research"
        static let decide = "Decide"
        static let paid = "Paid AI"
        static let add = "Add to backlog"
        static let addHelp = "Keep a task or an idea for later, with why it matters"
        static let titleLabel = "Task"
        static let titlePlaceholder = "The task, in a line"
        static let descriptionLabel = "Why"
        static let descriptionPlaceholder = "Why it matters — the problem, what you saw, what a fix must respect (optional)"
        static let reading = "Reading the backlog…"
        static let readingItem = "Reading the item…"
        static let failedTitle = "The backlog didn't load"
        static let itemFailedTitle = "This item didn't load"
        static let gone = "This item isn't on the project's backlog any more."
        static let saveFailed = "That change wasn't saved. Try again in a moment."
        static let description = "Description"
        static let noDescription = "No description yet."
        static let notes = "Notes"
        static let noNotes = "No notes yet."
        static let links = "Links"
        static let addNote = "Add a note"
        static let notePlaceholder = "What you found, decided or measured"
        static let saveNote = "Add note"
        static let saveNoteHelp = "Add this note, signed as you"
        static let editTitle = "Edit title"
        static let editTitleHelp = "Change how the task is worded"
        static let saveTitle = "Save"
        static let closeHelp = "Close the item"
        static let start = "Start"
        static let markDone = "Mark done"
        static let drop = "Drop"
        static let reopen = "Reopen"
        static let startHelp = "Mark it as being worked on"
        static let markDoneHelp = "Mark it done"
        static let dropHelp = "Set it aside for good — it stays under All"
        static let reopenHelp = "Put it back on the open list"
        static let emptyOpen = "Nothing open."
        static let emptyDoing = "Nothing in progress."
        static let emptyDone = "Nothing done yet."
        static let emptyDropped = "Nothing set aside."
        static let emptyAll = "Nothing on this backlog yet. Add a task, or ask an agent to put one here."

        static func openCount(_ n: Int) -> String { "\(UsageFormat.count(n)) open" }
        static func notesTitle(_ n: Int) -> String { n == 0 ? notes : "\(notes) · \(UsageFormat.count(n))" }
        static func addedBy(_ who: String) -> String { "Added by \(who)" }
        static func addedBy(_ who: String, day: String) -> String { "Added by \(who) · \(day)" }
        static func rowHelp(_ id: String) -> String { "Open \(id)" }
        static func itemHelp(_ id: String, path: String) -> String { path.isEmpty ? id : "\(id) · \(path)" }
        static func pullRequest(_ ref: String) -> String { "Pull request \(ref)" }

        /// A turn's reasoning effort in words (round 4's C1 enum: minimal, low, medium, high, xhigh, max).
        static func effort(_ raw: String) -> String {
            switch raw.lowercased() {
            case "xhigh": "extra-high effort"
            case "max": "maximum effort"
            default: "\(raw.lowercased()) effort"
            }
        }
    }
}
