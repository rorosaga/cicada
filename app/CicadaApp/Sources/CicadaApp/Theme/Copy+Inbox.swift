import Foundation

/// DS-2 — every sentence the Inbox's columns say, in one place (DR-59: sentence case, plain verbs,
/// no "!", no bare "%", no ids — DR-54). Its own file for the reason `Copy+Provenance.swift` gives:
/// parallel tracks edit `Copy.swift`.
extension Copy {
    enum Inbox {
        static let title = "Inbox"
        static func pending(_ n: Int) -> String { "\(UsageFormat.count(n)) pending" }
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static let all = "All"
        /// The kinds that did not fit, under one menu (owner 2026-10-16).
        static let moreKinds = "More kinds"

        // The list in groups (owner 2026-10-26): a kind's group, and the page two or more questions are about.
        static let groupOpenHelp = "Show these questions"
        static let groupCloseHelp = "Hide these questions"
        static func groupSpoken(_ kind: String, _ n: Int) -> String { "\(kind), \(UsageFormat.count(n)) questions" }
        static let groupReview = "Review one at a time"
        /// What a kind's questions ask, in one plain sentence, under its open group (inbox v2, owner 2026-10-26: a
        /// first-time reader should not need to know what "decay" or a "fold" is). Says what each answer does.
        static func kindExplainer(_ kind: InboxKind) -> String {
            switch kind {
            case .decay: "Pages you haven't mentioned in a while. Keep the ones that still matter; the rest fade and come back the next time you mention them."
            case .conflict: "Two things on record disagree. Pick the one that's true now, or keep both."
            case .clarification: "Names and details Cicada couldn't place on its own. Answer in a few words, or skip."
            case .mergeSuggestion: "Two names that may be the same thing. Merge them into one page, or keep them apart."
            case .divergence: "An agent wrote something different from what you said. Your words stay unless you change them."
            case .normalization: "Two ways of saying the same relation. Say whether they mean the same thing."
            case .removal: "Bookmarks you removed from your browser. Keep the saved page, or archive it."
            case .followup: "Plans that went quiet or passed their date. Say how they went."
            case .pageEdit: "Changes an agent proposed to a page's words. Apply each one, or dismiss it."
            case .agentRequest: "Things an agent needs you to do."
            case .unknown: "Questions from a newer version of Cicada."
            }
        }
        static func pageQuestions(_ n: Int) -> String { "\(UsageFormat.count(n)) questions" }

        // "Settled by a check" (owner ruling 2026-10-16): questions a web lookup or the person's agent answered.
        static let settledTitle = "Settled by a check"
        static func settledHeader(_ n: Int) -> String { "Settled by a check · \(UsageFormat.count(n))" }
        static let settledShowHelp = "Show the questions a check answered, with where each answer came from"
        static func settledFrom(_ host: String, _ when: String) -> String { "From \(host) · \(when)" }
        static func settledMeta(_ host: String, _ when: String, _ who: String) -> String {
            "\(settledFrom(host, when)) · \(who)"
        }
        static func settledAnswer(_ name: String, _ answer: String) -> String { "\(name) — \(answer)" }
        static func settledQuote(_ quote: String) -> String { "\u{201C}\(quote)\u{201D}" }
        static let settledByAgent = "your agent looked it up"
        static let settledBySleep = "looked up while reading your memory"
        static let settledUndo = "Undo"
        static let settledUndoHelp = "Put the question back and take back only what this check wrote"
        static let settledTrack = "Track this source"
        static let settledTrackHelp = "Add this page to the places Cicada re-checks for this page's facts"
        static let settledTracked = "Tracked"
        static let settledUndoFailed = "That check couldn't be undone. It's still settled."
        // Ruling 29 — "Settled by Sleep": what Sleep answered from the person's own words, or assumed.
        static let settledSleepTitle = "Settled by Sleep"
        static func settledSleepHeader(_ n: Int) -> String { "Settled by Sleep · \(UsageFormat.count(n))" }
        static let settledSleepShowHelp = "Show the questions Sleep answered from your conversations or assumed for you"
        static func settledSleepMeta(_ reason: String, _ when: String) -> String {
            reason.isEmpty ? when : "\(reason) · \(when)"
        }
        static let settledSleepUndoHelp = "Put the question back and take back what Sleep changed for it"
        static let settledSleepUndoFailed = "That couldn't be undone — the page changed since. Answer the question there instead."
        static let settledTrackFailed = "That page couldn't be added as a source."

        // The Undo row (R-DI5)
        static let answered = "Answered"
        static func answered(_ what: String) -> String { "Answered · \(what)" }
        static let notNow = "Not now"
        static let gotIt = "Got it"
        static let dismissed = "Dismissed"
        static let skipped = "Skipped"
        static let keptSeparate = "Kept separate"
        static let kept = "Kept"
        static let merged = "Merged"
        static let archived = "Archived"
        static let undo = "Undo"
        static let undoHelp = "Undo (⌘Z)"
        /// R-DI3 — another client moved the active bank inside the window.
        static let answerNotSaved = "Your last answer wasn't saved because the memory bank changed. It's still in the inbox."

        // The focus card (Task 3 — DR-41, DR-42, DR-43, DR-54, R-DI12, R-DI15)
        static func aConversation(_ app: String) -> String { "a \(app) conversation" }
        static let aConversationPlain = "a conversation"
        static let noSourceAge = "No source recorded, so no date to measure from"
        static let recommended = "Recommended"
        static let other = "Other…"
        static let otherPrompt = "What's actually true?"
        static let answerPrompt = "Type your answer…"
        static let namePrompt = "Their name…"
        static let nameNeedsText = "Type their name first"
        static let ratherNotSay = "I'd rather not say"
        static let ratherNotSayHelp = "Keep this person under the relation; Cicada won't ask again"
        static let submit = "Submit"
        /// DR-41 — a disabled control says why in `.help`.
        static let submitNeedsText = "Type what's actually true first"
        static let answerNeedsText = "Type an answer first"
        static let mergeNeedsTarget = "Name the existing entity first"
        static func pressKey(_ n: Int) -> String { "Press \(n)" }
        static let notNowSevenDays = "Not now — ask again in 7 days"
        static let notNowHelp = "Ask again in 7 days (L)"
        static let close = "Close (Esc)"
        static let showConversationHelp = "Open the conversation beside this question"
        static let hideConversation = "Hide conversation"
        static let hideConversationHelp = "Close the conversation (Esc)"
        // G61 S3 — what an agent reported from a source (a report, never an answer)
        static let checkedByAgent = "Your agent"
        static let checkedByApp = "An app you connected"
        static let checkedASource = "a source"
        static func checkedHeading(who: String, host: String, day: String) -> String { "\(who) looked at \(host) · \(day)" }
        static func checkedHeadingNoDay(who: String, host: String) -> String { "\(who) looked at \(host)" }
        static func checkSupports(_ label: String) -> String { "It points to “\(label)”." }
        static let checkSupportsAnOption = "It points to one of these answers."
        static func checkProposes(_ value: String) -> String { "It suggests another answer: “\(value)”." }
        static let checkProposesAnother = "It suggests another answer."
        static let checkContradicts = "It doesn’t match any of these answers."
        static let checkUnclear = "It wasn’t clear."
        static let checkCaption = "What your agent reported, not checked by Cicada. Nothing changed; you decide."
        static let checkCaptionApp = "What an app you connected reported, not checked by Cicada. Nothing changed; you decide."
        static let openSource = "Open source"
        /// Round-4 final review, finding 3: a Contacts card opens in Contacts, and the button says where it goes.
        static let openInContacts = "Open in Contacts"
        static let openInContactsHelp = "Open their card in Contacts"
        static func openSourceHelp(_ where: String) -> String { "Open \(`where`)" }
        /// Looks pass (2026-10-23): the sentence named the raw predicate ("works-at holds several values"); the values
        /// are listed right under it, so the plain claim is enough.
        static let informational = "These can all be true at once. Nothing to pick."
        static let describeEntity = "Describe this entity"
        static let describePrompt = "Describe this entity…"
        static let existingEntity = "Existing entity"
        static let existingPrompt = "Existing entity…"
        static let keepAsCanonical = "Keep as canonical"
        static let newFromExtraction = "Newly noticed"
        static let existingPage = "Existing page"
        static let answer = "Answer"
        static let merge = "Merge"
        static let keepSeparate = "Keep separate"
        static let skip = "Skip"
        static let dismiss = "Dismiss"
        static let keepActive = "Keep active"
        static let archive = "Archive"
        static func questions(_ n: Int) -> String { n == 1 ? "‹ 1 question" : "‹ \(UsageFormat.count(n)) questions" }
        static let showQuestions = "Show the questions"
        static let showFewer = "Show fewer"
        static func showAll(_ n: Int) -> String { "Show all \(UsageFormat.count(n))" }
        static let openQuestion = "Open this question"
        static func openPageHelp(_ name: String) -> String { "Open \(name)'s page" }

        // The columns (Task 5 — DR-43, DR-50, R-DI10): the page states keep their pre-DS-2 words.
        static let dot = "·"
        /// VoiceOver hears the kind, the question, and whether it is the one open beside the list.
        static func rowAccessibility(kind: String, question: String, open: Bool) -> String {
            (open ? "Open: " : "") + kind + " — " + question
        }
        static let checking = "Checking what needs you…"
        static let loadFailed = "Couldn't load the inbox"
        static let retry = "Retry"
        static let nothingPending = "Nothing pending"
        static func lastSleep(_ phrase: String) -> String { "Last Sleep cycle \(phrase)." }
        static let sleepNotRun = "Sleep has not run yet, so nothing has been asked."
        static func waiting(_ n: Int) -> String {
            "\(UsageFormat.count(n)) conversation\(n == 1 ? "" : "s") waiting for the next cycle."
        }
    }
}

extension Copy.Inbox {
    /// A possible duplicate, in plain words (inbox v2, owner 2026-10-26: "I don't really get … possible duplicates").
    /// Merge's sentence is what the backend's merge does (`inbox_service._resolve_clarification`): the name becomes
    /// another name of the existing page, and a page of its own folds into it.
    enum Duplicate {
        static let newName = "Name from a conversation"
        static let existingPage = "Existing page"
        static let noPageYet = "No page yet — only mentioned in a conversation."
        static let noSummary = "No summary yet."
        static func mergeNames(_ mention: String, _ existing: String) -> String {
            "Merge files \u{201C}\(mention)\u{201D} under \(existing) as another name for it."
        }
        static func mergeFolds(_ mention: String, _ existing: String) -> String {
            "Merge folds \u{201C}\(mention)\u{201D} into \(existing): its facts, links and mentions move there, and its name stays as another name."
        }
        static let keepWords = "Keep separate, and Cicada won't suggest this pair again."
        static let undoWords = "Each answer can be undone for a few seconds after."
        static let noTarget = "Cicada didn't say which page this could be. Name it below."
        static let somethingElse = "Something else"
        static let somethingElseHelp = "Describe it instead, merge with a different page, or keep the other name"
        static let mergeHelp = "Join the two into one page"
        static let keepHelp = "They're different; don't ask about this pair again"
    }

    /// The quick review (owner 2026-10-19): one kind at a time, the same answers in the same place.
    enum Review {
        static func kindTitle(_ kind: ReviewKind) -> String {
            switch kind {
            case .decay: "Fading pages"
            case .fold: "Folds"
            case .conflict: "Conflicts"
            case .question: "Questions"
            }
        }
        static let entriesLabel = "Review one kind at a time"
        static func entry(_ kind: ReviewKind, _ n: Int) -> String { "\(kindTitle(kind)) · \(UsageFormat.count(n))" }
        static func entryHelp(_ kind: ReviewKind) -> String {
            switch kind {
            case .decay: "Go through the pages that are fading, one at a time: keep or let fade"
            case .fold: "Go through the predicate folds, one at a time: same or different"
            case .conflict: "Go through the conflicts, one at a time: one side, the other, or both"
            case .question: "Go through the open questions, one at a time: type an answer or skip"
            }
        }
        static let review = "Review"
        static func position(_ i: Int, of n: Int) -> String { Copy.Inbox.position(i, of: n) }
        static func progress(answered: Int, skipped: Int, left: Int) -> String {
            "\(UsageFormat.count(answered)) answered · \(UsageFormat.count(skipped)) skipped · "
                + "\(UsageFormat.count(left)) left"
        }
        static let end = "End review"
        static let endHelp = "Back to the Inbox (Esc). Skipped questions stay there."
        static let openInInbox = "Open in Inbox"
        static let openInInboxHelp = "Answer this one in the Inbox's full card — another answer, not now, the conversation"
        static let skip = "Skip"
        static let skipHelp = "Leave it in the Inbox and go to the next one (S)"
        static let undo = "Undo"
        static let undoHelp = "Take back the last answer or skip (⌘Z)"

        // Decay
        static let keep = "Keep"
        static let keepDetail = "Still relevant — it stays active"
        static let letFade = "Let fade"
        static let letFadeDetail = "Archived; it comes back the next time it's mentioned"
        static func lastSaid(day: String?, age: String?) -> String {
            switch (day, age) {
            case let (day?, age?): "Last said \(day) · \(age)"
            case let (day?, nil): "Last said \(day)"
            case let (nil, age?): "Last said \(age)"
            default: "Last said: not recorded"
            }
        }
        static func conversations(_ n: Int) -> String {
            switch n {
            case 0: "In no dated conversation"
            case 1: "In 1 conversation"
            default: "In \(UsageFormat.count(n)) conversations"
            }
        }

        // Folds
        static func foldQuestion(_ raw: String, _ canonical: String) -> String {
            "Is \u{201C}\(raw)\u{201D} the same as \u{201C}\(canonical)\u{201D}?"
        }
        static func foldCovers(claims: Int, pages: Int) -> String {
            let c = claims == 1 ? "1 fact" : "\(UsageFormat.count(claims)) facts"
            let p = pages == 1 ? "1 page" : "\(UsageFormat.count(pages)) pages"
            return "Covers \(c) on \(p)"
        }
        static let forExample = "For example"
        static let same = "Same"
        static func sameDetail(_ raw: String, _ canonical: String) -> String {
            "File \u{201C}\(raw)\u{201D} under \u{201C}\(canonical)\u{201D}"
        }
        static let different = "Different"
        static func differentDetail(_ raw: String) -> String { "Keep \u{201C}\(raw)\u{201D} as its own" }

        // Conflicts
        static let both = "Both"
        static func said(day: String?, age: String?) -> String? {
            switch (day, age) {
            case let (day?, age?): "Said \(day) · \(age)"
            case let (day?, nil): "Said \(day)"
            case let (nil, age?): "Said \(age)"
            default: nil
            }
        }

        // The end
        static let finished = "That's the last one"
        static func finishedDetail(answered: Int, skipped: Int) -> String {
            let a = "\(UsageFormat.count(answered)) answered"
            guard skipped > 0 else { return "\(a)." }
            return "\(a), \(UsageFormat.count(skipped)) skipped — skipped questions stay in the Inbox."
        }
        static let backToInbox = "Back to the Inbox"
    }
}
