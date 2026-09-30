import Foundation

/// Sleep page v5 (G163; TODO rulings 13, 15, 16): every string the run's new surfaces say — the sentence ladder's
/// new rungs, Pause / Continue / End this run, the strip's captions and the progress bar, Reading options, the
/// engine menu's *Keep plan free*, Details and Past nights, and the doors. Its own file for the reason
/// `Copy+HomeSleep` gives: one file per track.
///
/// Three rules hold here, each by a lint:
///  1. **Provider-neutral** (owner, 2026-09-30): no string names a provider or a model as the one doing a job. A
///     step is described ("the engine you chose"); a name appears only where it is the person's own current
///     choice, passed in as data (`SleepProviderNeutralLintTests`).
///  2. **Nothing is "read and kept"**: there is no journal (G163 SL-1), so a pause or a hard plan rejection mid-batch
///     reads that batch again, and no string says otherwise (`SleepV5RoomSentenceTests`).
///  3. **Ruling 12**: a plan's percentage, a price or a token count appears only in Details and the engine menu —
///     the reserve's figure is the one percentage here, and it is rendered only there (`PriceLintTests`).
/// Short labels join `sleepV5Labels`, which `HomeSleepCopyTests`' rules read too.
extension Copy {
    enum SleepV5 {
        // MARK: Counting words

        static func count(_ n: Int, _ locale: Locale) -> String { UsageFormat.count(n, locale: locale) }
        static func conversations(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "conversation" : "conversations")"
        }
        static func filedOf(_ filed: Int, _ frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(filed, locale)) of \(count(frozen, locale)) filed"
        }

        // MARK: The sentence ladder (lead ≤ 40, tail ≤ 80, clock-free: every time arrives as words)

        static func firstNightTail(batchSize: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "My first night. I'll read all of them, saving every \(count(batchSize, locale))."
        }
        static func sortingLead(_ done: Int, _ total: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Sorting \(count(done, locale)) of \(count(total, locale))."
        }
        static let sortingTail = "Matching new names to what you have."
        static func decidingLead(_ done: Int, _ total: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Deciding \(count(done, locale)) of \(count(total, locale))."
        }
        static let decidingTail = "Checking pages for contradictions."
        static let filingLead = "Filing…"
        static func firstSaveTail(filed: Int, beliefs: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Filed the first \(count(filed, locale)). Your page has \(count(beliefs, locale)) \(beliefs == 1 ? "belief" : "beliefs") so far."
        }
        static let pausingLead = "Pausing."
        /// Never "nothing read is lost": without a journal the part in progress is read again.
        static let pausingTail = "Stopping at the next safe point. What is filed stays filed."
        static let pausedLead = "Paused."
        static func pausedByYouTail(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(filedOf(filed, frozen, locale)). The part it was reading is read again."
        }
        static let pausedReserveLead = "Paused to leave room in your plan."
        static func continueWhenYouLike(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Continue when you like. \(filedOf(filed, frozen, locale))."
        }
        static func continuesAfter(_ when: String, filed: Int, frozen: Int,
                                   _ locale: Locale = .autoupdatingCurrent) -> String {
            "Continues after \(when). \(filedOf(filed, frozen, locale))."
        }
        static func willContinueBySelf(_ when: String) -> String {
            "Will continue by itself after \(when). You said so for the runs you start."
        }
        static let pausedPlanWindowLead = "Paused. Your plan window is full."
        static let pausedPlanWeeklyLead = "Paused. Your plan's week is used up."
        static let pausedOverageLead = "Paused at your plan's limit."
        static func resetsContinue(_ when: String) -> String { "Resets \(when). Continue when you like." }
        static func resetsThenContinue(_ when: String) -> String { "Resets \(when). Continue then." }
        static let continueWhenItResets = "Continue when your plan resets."
        static let pausedEngineLead = "Paused. The engine needs a look."
        static func continueWhenFixed(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Continue when it is fixed. \(filedOf(filed, frozen, locale))."
        }
        static let restartLead = "Cicada restarted while reading."
        static func restartTail(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(filedOf(filed, frozen, locale)). Continue when you like."
        }
        /// Unreachable today (a run refuses a bank switch); kept so the rung has words if it ever is.
        static let bankSwitchedLead = "Paused. You switched memory."
        static let bankSwitchedTail = "Continue when you switch back."
        static func filedLead(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Filed \(conversations(n, locale))."
        }
        static func parkedLine(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(conversations(n, locale).capitalizedFirst) could not be read. See What's waiting in Details."
        }
        static func newSinceYouStarted(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) new since you started"
        }

        // MARK: Controls

        static let pause = "Pause"
        static let pausing = "Pausing…"
        static let continueRun = "Continue"
        static let endRun = "End this run"
        static let readingOptions = "Reading options…"
        static let seeYourPage = "See your page ›"
        static let retry = "Retry"
        static let pauseHelp = "Stops at the next safe point. What is filed stays filed; the part it was reading is read again."
        static func continueHelp(_ engine: String) -> String { "Continues this run on \(engine)." }
        static let continueHelpGeneric = "Continues this run on the engine you chose."

        static let endRunHelp = "Forgets this pause. Nothing waiting changes, and Consolidate now starts a new run."
        static let continueFailed = "Couldn't continue the run — nothing changed."
        static let endRunFailed = "Couldn't end the run — nothing changed."
        static let retryFailed = "Couldn't retry — nothing changed."
        static func runningFor(_ duration: String) -> String { "Running \(duration)" }
        static let pausedAnnouncement = "Sleep paused."
        static let continuedAnnouncement = "Sleep continued."

        // MARK: The strip and the bar

        static let readingCaption = "Reading conversations"
        static let couldNotBeReadPhrase = "could not be read"
        static func couldNotBeRead(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(couldNotBeReadPhrase)"
        }
        static let oneMoreTry = "it gets one more try"
        static func sortingCaption(read: Int, failed: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            var text = "Sorting names · \(count(read, locale)) read"
            if failed > 0 { text += ", \(couldNotBeRead(failed, locale))" }
            return text
        }
        static func decidingCaption(pages: Int?, _ locale: Locale = .autoupdatingCurrent) -> String {
            guard let pages else { return "Deciding" }
            return "Deciding · \(count(pages, locale)) \(pages == 1 ? "page" : "pages") to update"
        }
        static let noticingCaption = "Noticing what repeats"
        static let filingCaption = "Filing. It cannot be stopped now."
        static func filed(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "\(count(n, locale)) filed" }
        static func readWaitingToFile(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) read, waiting to file"
        }
        static func waiting(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "\(count(n, locale)) waiting" }
        static func callsMade(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "call" : "calls") made"
        }
        static func batches(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "batch" : "batches")"
        }
        static func pauses(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "pause" : "pauses")"
        }
        static let progressLabel = "Run progress"

        // MARK: Reading options

        static let optionsTitle = "Reading options"
        static func optionsIntro(waiting: Int, batchSize: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Consolidate now reads all \(count(waiting, locale)) waiting \(waiting == 1 ? "conversation" : "conversations"), "
                + "oldest first, and files them as it goes. It saves every \(count(batchSize, locale)), so a pause, "
                + "a quit or a plan limit loses at most the part it was reading."
        }
        static let whatItReads = "What it reads"
        static func conversationsAndNotes(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Conversations and notes · \(count(n, locale))"
        }
        static let saveProgressEvery = "Save progress every"
        static func everyN(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { conversations(n, locale) }
        static func savesFor(saves: Int, waiting: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(saves, locale)) \(saves == 1 ? "save" : "saves") for \(conversations(waiting, locale))."
        }
        static let runsOn = "Runs on"
        static let leaveRoom = "Leave room in my plan"
        static let setInEngineMenu = "Set in the engine menu ›"
        static let leaveRoomHelp = "Stops starting new reads before your plan window fills. Set it in the engine menu beside Consolidate now."
        static let continueAfterReset = "Continue by itself when my plan resets"
        static let continueAfterResetCaption =
            "For the runs you start. At most twice, within 36 hours, and never past a weekly limit."
        static func scheduledReadsAll(engine: String, billing: String?) -> String {
            ["Scheduled runs read everything waiting too, on \(engine).", scheduledSpend(billing)]
                .compactMap { $0 }.joined(separator: " ")
        }
        static let optionsNote =
            "Each conversation takes several calls to the engine you chose. The count is shown while it runs. You can pause any time."
        static let cancel = "Cancel"
        static let optionsWriteFailed = "Couldn't save that — nothing changed."

        // MARK: The engine menu (ruling 12's home for the reserve's figure)

        static let keepPlanFree = "Keep plan free"
        static let off = "Off"
        static func reserveChoice(_ pct: Int) -> String { "\(pct)% of the window" }
        static func reserveValue(_ pct: Int, windows: [String]) -> String {
            guard !windows.isEmpty else { return "\(pct)% of each window it reports" }
            return "\(pct)% of the \(windows.joined(separator: " and the "))"
        }
        static func reserveNotReported(_ window: String) -> String {
            "Your \(window) isn't reported by this engine, so it can't be kept free."
        }
        static let reserveHelp =
            "Sleep stops starting new reads once a window passes this line. Reads already running finish, so it is a line, not a guarantee."
        /// How a scheduled run spends (ruling 16), from `preview.scheduled.billing` — never a provider name.
        static func scheduledSpend(_ billing: String?) -> String? {
            switch billing {
            case "charged": "It reads everything waiting and is charged per use; Cicada sets no limit."
            case "local": "It reads everything waiting, on this Mac."
            default: nil
            }
        }
        static let scheduledNeverSpendsPlans =
            "Scheduled cycles never use a plan you signed in to — only a cycle you start yourself does."

        // MARK: Details

        static let runLiveTitle = "Reading all · in progress"
        static let runDoneTitle = "Reading all · finished"
        static let runStoppedTitle = "Reading all · stopped"
        static func runLiveText(filed: Int, frozen: Int, batches: Int, calls: Int?,
                                _ locale: Locale = .autoupdatingCurrent) -> String {
            var text = "\(filedOf(filed, frozen, locale)) in \(self.batches(batches, locale)) so far"
            if let calls { text += " · \(count(calls, locale)) \(calls == 1 ? "call" : "calls")" }
            return text
        }
        static func runDoneText(filed: Int, frozen: Int, batches: Int, pauses: Int, readFor: String?,
                                pausedFor: String?, _ locale: Locale = .autoupdatingCurrent) -> String {
            var text = "\(filedOf(filed, frozen, locale)) in \(self.batches(batches, locale))"
            if pauses > 0 { text += ", \(self.pauses(pauses, locale))" }
            var times: [String] = []
            if let readFor { times.append("read for \(readFor)") }
            if let pausedFor, pauses > 0 { times.append("paused \(pausedFor)") }
            if !times.isEmpty { text += " · " + times.joined(separator: ", ") }
            return text
        }
        static func scheduledRunNote(_ billing: String?) -> String? {
            guard billing == "charged" else { return nil }
            return "This run started on its schedule. It spends until the queue is empty; Cicada sets no limit."
        }
        static func ownerBeliefsTitle(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Your page has \(count(n, locale)) \(n == 1 ? "belief" : "beliefs")"
        }
        static func ownerBeliefsText(atStart: Int?, afterFirstBatch: Int?, firstBatch: Int,
                                     _ locale: Locale = .autoupdatingCurrent) -> String? {
            var parts: [String] = []
            if let atStart { parts.append(atStart == 0 ? "It had none when the run began." : "It had \(count(atStart, locale)) when the run began.") }
            if let after = afterFirstBatch, after > (atStart ?? 0) {
                parts.append("\(count(after - (atStart ?? 0), locale)) came from the first \(conversations(firstBatch, locale)).")
            }
            return parts.isEmpty ? nil : parts.joined(separator: " ")
        }
        static let ownerReadyTitle = "Your own page is ready"
        static let ownerReadyText = "It fills as Cicada reads."
        static func newPages(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) new \(n == 1 ? "page" : "pages")"
        }
        static func questionsForYou(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "question" : "questions") for you"
        }
        static let parkedTitle = "Could not be read"
        static func parkedText(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(conversations(n, locale).capitalizedFirst) failed twice and \(n == 1 ? "waits" : "wait") for you. Retry reads \(n == 1 ? "it" : "them") again."
        }
        static func pausedTitle(_ reason: String) -> String {
            switch reason {
            case "user": "Paused by you"
            case "reserve": "Paused to leave room in your plan"
            case "plan_window", "plan_weekly", "overage": "Paused at your plan's limit"
            case "engine": "Paused — the engine stopped"
            case "restart": "Paused — Cicada restarted"
            case "bank_switched": bankSwitchedLead
            default: "Paused"
            }
        }
        static func pausedReserveText(batch: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Batch \(count(batch, locale)) stopped starting new reads. What it had read was filed."
        }
        static func pausedText(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(filedOf(filed, frozen, locale)). The rest wait until you continue or end this run."
        }
        static func keepPlanFreeIs(_ value: String) -> String { "Keep plan free is \(value), set in the engine menu." }
        static func sourceLine(filed: Int, read: Int, waiting: Int, couldNotBeRead: Int, parked: Int,
                               _ locale: Locale = .autoupdatingCurrent) -> String {
            var parts: [String] = []
            if filed > 0 { parts.append(SleepV5.filed(filed, locale)) }
            if read > 0 { parts.append("\(count(read, locale)) read") }
            if waiting > 0 { parts.append(SleepV5.waiting(waiting, locale)) }
            if couldNotBeRead + parked > 0 { parts.append(SleepV5.couldNotBeRead(couldNotBeRead + parked, locale)) }
            return parts.joined(separator: " · ")
        }
        static func reasonWords(_ reason: String?) -> String {
            switch reason {
            case "empty_answer": "the answer came back empty"
            case "timed_out": "it took too long"
            case "unparseable": "the answer could not be understood"
            case "refused": "the engine declined it"
            default: "something went wrong"
            }
        }
        static func queueStateWords(state: String, reason: String?, attempts: Int) -> String {
            switch state {
            case "reading": "reading"
            case "read": "read"
            case "filed": "filed"
            case "could_not_be_read": "could not be read · \(reasonWords(reason)) · \(oneMoreTry)"
            case "parked": attempts >= 2 ? "\(reasonWords(reason)) twice" : reasonWords(reason)
            default: "waiting"
            }
        }
        static func showAll(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "Show all \(count(n, locale))" }
        /// Critic M2: the reader opens saved pages during a run, and Cicada picks no sites — a page that needs the
        /// person's browser waits for them. It names neither a provider nor a site list.
        static let readerNote =
            "While it runs, the reader also opens saved pages it can. Pages that need your browser wait for your say-so."

        // MARK: Past nights and the run

        static let readingAll = "Reading all"
        static func groupSummary(filed: Int, batches: Int, pauses: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            var parts = [conversations(filed, locale), self.batches(batches, locale)]
            if pauses > 0 { parts.append(self.pauses(pauses, locale)) }
            return parts.joined(separator: " · ")
        }
        static func groupTimes(readFor: String?, pausedFor: String?, parked: Int,
                               _ locale: Locale = .autoupdatingCurrent) -> String? {
            var text: [String] = []
            if let readFor {
                text.append(pausedFor.map { "Read for \(readFor), paused \($0)." } ?? "Read for \(readFor).")
            }
            if parked > 0 { text.append("\(conversations(parked, locale).capitalizedFirst) could not be read.") }
            return text.isEmpty ? nil : text.joined(separator: " ")
        }
        static let batchesTitle = "Batches"
        static let pagesItTouched = "Pages it touched"
        static let whatHappened = "What happened"
        static let took = "Took"
        static let calls = "Calls"
        static let window = "Window"
        static func batchRow(_ index: Int, filed: Int, notFiled: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            var text = "Batch \(count(index, locale)) · \(self.filed(filed, locale))"
            if notFiled > 0 { text += " · \(count(notFiled, locale)) not filed" }
            return text
        }
        static func pauseRow(from: String, to: String?, reason: String) -> String {
            let span = to.map { "Paused \(from) to \($0)" } ?? "Paused at \(from)"
            return "\(span) · \(pauseReasonWords(reason))"
        }
        static func pauseReasonWords(_ reason: String) -> String {
            switch reason {
            case "user": "you paused it"
            case "reserve": "to leave room in your plan"
            case "plan_window", "plan_weekly", "overage": "the plan's limit"
            case "engine": "the engine stopped"
            case "restart": "Cicada restarted"
            default: "paused"
            }
        }
        static func pagesSummary(created: Int, ownerTouched: Bool?, _ locale: Locale = .autoupdatingCurrent) -> String {
            ownerTouched == true ? "\(newPages(created, locale)) and your own page." : "\(newPages(created, locale))."
        }
        static let runLoading = "Loading the run…"
        static let runNotRecorded = "This run's detail was not recorded."
        /// A ledger stage in the page's own words; `nil` for one the page has no word for (never a guess).
        static func stageWord(_ stage: String) -> String? {
            switch stage {
            case "extraction": "Read"
            case "disambiguation", "dedup": "Sort"
            case "conflict", "merge", "reconcile": "Decide"
            case "skills", "structural": "Notice"
            default: nil
            }
        }

        // MARK: Doors

        static func consolidateAll(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            n > 0 ? "Consolidate now — all \(count(n, locale))" : Copy.consolidateNow
        }
        static let continueOnSleepPage = "Continue on the Sleep page…"
        static func pausedMenuTitle(filed: Int, frozen: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Paused — \(filedOf(filed, frozen, locale))"
        }
        static func readNowCaption(waiting: Int, batchSize: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Reads all \(count(waiting, locale)) waiting, oldest first, saving every \(count(batchSize, locale)). Follow along on the Sleep page."
        }
        static let pausedDoorCaption = "A run is paused. Continue it on the Sleep page."
    }

    /// DR-59 over the v5 labels (short, plain, sentence case, priceless) — read by `HomeSleepCopyTests`' rules.
    static let sleepV5Labels: [String] = [
        SleepV5.pause, SleepV5.pausing, SleepV5.continueRun, SleepV5.endRun, SleepV5.readingOptions,
        SleepV5.seeYourPage, SleepV5.retry, SleepV5.optionsTitle, SleepV5.whatItReads, SleepV5.saveProgressEvery,
        SleepV5.runsOn, SleepV5.leaveRoom, SleepV5.setInEngineMenu, SleepV5.continueAfterReset, SleepV5.cancel,
        SleepV5.keepPlanFree, SleepV5.off, SleepV5.runLiveTitle, SleepV5.runDoneTitle, SleepV5.runStoppedTitle,
        SleepV5.ownerReadyTitle, SleepV5.parkedTitle, SleepV5.readingAll, SleepV5.batchesTitle,
        SleepV5.pagesItTouched, SleepV5.whatHappened, SleepV5.took, SleepV5.calls, SleepV5.window,
        SleepV5.continueOnSleepPage, SleepV5.readingCaption, SleepV5.filingLead, SleepV5.pausingLead,
        SleepV5.pausedLead, SleepV5.pausedTitle("reserve"), SleepV5.pausedTitle("user"),
        SleepV5.pausedTitle("plan_window"), SleepV5.pausedTitle("engine"), SleepV5.pausedTitle("restart"),
        SleepV5.consolidateAll(287), SleepV5.pausedMenuTitle(filed: 98, frozen: 287),
    ]

    /// Every sentence the ladder can speak with sample numbers — the neutrality, "read and kept" and length lints
    /// read this list (`SleepV5RoomSentenceTests`, `SleepProviderNeutralLintTests`).
    static let sleepV5Sentences: [String] = [
        SleepV5.firstNightTail(batchSize: 25), SleepV5.sortingLead(31, 86), SleepV5.sortingTail,
        SleepV5.decidingLead(4, 12), SleepV5.decidingTail, SleepV5.filingLead,
        SleepV5.firstSaveTail(filed: 25, beliefs: 31), SleepV5.pausingLead, SleepV5.pausingTail, SleepV5.pausedLead,
        SleepV5.pausedByYouTail(filed: 74, frozen: 287), SleepV5.pausedReserveLead,
        SleepV5.continueWhenYouLike(filed: 98, frozen: 287), SleepV5.continuesAfter("3:40 PM", filed: 98, frozen: 287),
        SleepV5.willContinueBySelf("3:40 PM"), SleepV5.pausedPlanWindowLead, SleepV5.pausedPlanWeeklyLead,
        SleepV5.pausedOverageLead, SleepV5.resetsContinue("after 2:00 PM"), SleepV5.resetsThenContinue("Tue 2:00 PM"),
        SleepV5.continueWhenItResets, SleepV5.pausedEngineLead, SleepV5.continueWhenFixed(filed: 98, frozen: 287),
        SleepV5.restartLead, SleepV5.restartTail(filed: 98, frozen: 287), SleepV5.bankSwitchedLead,
        SleepV5.bankSwitchedTail, SleepV5.filedLead(286), SleepV5.parkedLine(1),
        SleepV5.pauseHelp, SleepV5.endRunHelp, SleepV5.optionsIntro(waiting: 287, batchSize: 25),
        SleepV5.continueAfterResetCaption, SleepV5.optionsNote, SleepV5.leaveRoomHelp, SleepV5.reserveHelp,
        SleepV5.scheduledSpend("charged") ?? "", SleepV5.scheduledSpend("local") ?? "",
        SleepV5.scheduledNeverSpendsPlans, SleepV5.readerNote, SleepV5.pausingTail,
        SleepV5.parkedText(1), SleepV5.pausedText(filed: 98, frozen: 287), SleepV5.pausedReserveText(batch: 5),
        SleepV5.scheduledRunNote("charged") ?? "", SleepV5.readNowCaption(waiting: 318, batchSize: 25),
        SleepV5.pausedDoorCaption, SleepV5.continueOnSleepPage, SleepV5.reserveNotReported("weekly window"),
        SleepV5.groupTimes(readFor: "2 h 14 m", pausedFor: "4 h 37 m", parked: 1) ?? "",
        SleepV5.ownerBeliefsText(atStart: 0, afterFirstBatch: 31, firstBatch: 25) ?? "",
        SleepV5.filingCaption, SleepV5.noticingCaption, SleepV5.sortingCaption(read: 24, failed: 1),
        SleepV5.decidingCaption(pages: 12),
    ]
}

extension String {
    /// The first letter up, the rest untouched — "1 conversation" stays "1 conversation", "one" becomes "One".
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
