import Foundation

/// G162 — every string of the video surfaces (the Feed's Videos tab, the picker and run card, the detail block, the
/// Sleep row). One file, so `VideoCopyNeutralityTests` scans it once. DR-59: sentence case, plain verbs, no "!", no
/// bare "%", no ids, no prices (ruling 12) and no tokens.
///
/// **Provider-neutral (owner 2026-09-30, R-VU11).** A string here describes the step ("an agent", "a model that takes
/// video") and never names a provider or a model as the one doing the job. An attribution ("Claude Code · Sep 28") is
/// built from DATA — the harness and model a record carries, through `OriginIconography.label` and `ModelNames` — so
/// no such name appears in this file, and the test that scans it fails if one does.
extension Copy {
    enum Videos {
        // MARK: The Videos tab and its strip
        static let savedVideos = "Saved videos"
        static let chooseVideos = "Choose videos…"
        static let chooseVideosHelp = "Pick videos for your agent to read or watch"
        static func unreadCount(_ n: Int) -> String { "\(UsageFormat.count(n)) not read yet" }
        static let noneUnread = "All read or queued"
        static let noSavedVideos = "Videos you save will show up here."
        static let everyVideoRead = "Every saved video has been read or watched."

        /// The one queue wording, used by the strip and the Sleep row: "4 queued · 1 picked up by an agent · 1 couldn't
        /// be done", a clause omitted at zero.
        static func queueLine(queued: Int, claimed: Int, failed: Int) -> String {
            var parts: [String] = []
            if queued > 0 { parts.append("\(UsageFormat.count(queued)) queued") }
            if claimed > 0 { parts.append(claimed == 1 ? "1 picked up by an agent" : "\(UsageFormat.count(claimed)) picked up by agents") }
            if failed > 0 { parts.append("\(UsageFormat.count(failed)) couldn't be done") }
            return parts.joined(separator: " · ")
        }

        /// The run's own meter line: what is left of a hand-off ("1 picked up by an agent · 1 waiting · 1 couldn't be done").
        static func meterLine(claimed: Int, waiting: Int, failed: Int) -> String {
            var parts: [String] = []
            if claimed > 0 { parts.append(claimed == 1 ? "1 picked up by an agent" : "\(UsageFormat.count(claimed)) picked up by agents") }
            if waiting > 0 { parts.append("\(UsageFormat.count(waiting)) waiting") }
            if failed > 0 { parts.append("\(UsageFormat.count(failed)) couldn't be done") }
            return parts.joined(separator: " · ")
        }

        // MARK: What Cicada has — the states (Tag words) and the row's trailing word
        static let stateNone = "Metadata only"
        static let stateTranscript = "Transcript read"
        static let stateWatched = "Watched by an agent"
        static let stateBoth = "Watched, with transcript"
        static let stateRecorded = "Recorded, method not given"
        static let rowTranscript = "Transcript"
        static let rowWatched = "Watched"
        static let rowBoth = "Both"
        static let rowRecorded = "Recorded"
        static let rowQueued = "Queued"
        static let rowPickedUp = "Picked up"
        static let rowCouldntDo = "Couldn't do"
        static let rowWaiting = "Waiting"

        // MARK: The block in a video's detail column
        static let blockTitle = "What Cicada has from this video"
        static let onlyMetadata = "Only the title and thumbnail so far."
        static let queueTranscript = "Queue transcript"
        static let queueWatch = "Queue watch"
        static let watchIncludesTranscript = "Watching includes the transcript"
        static let queueTranscriptForWording = "Queue a transcript for exact wording"
        static let remove = "Remove"
        static let removeHelp = "Take this video out of the queue"
        static let tryAgain = "Try again"
        static let openRecord = "Open the record ›"
        static let openRecordHelp = "Open the agent's record of this video"
        static let openInBrowser = "Open in browser"
        static let openInBrowserHelp = "Open the video's page to sign in yourself"
        static func inQueue(_ want: VideoWant) -> String {
            want == .watch ? "In the queue to be watched" : "In the queue to be read"
        }
        static func pickedUp(_ want: VideoWant) -> String { want == .watch ? "to watch" : "to read" }
        static func pickedUpBy(_ agent: String, want: VideoWant) -> String { "Picked up by \(agent) \(pickedUp(want))" }
        static func couldntDo(_ reason: String) -> String { "An agent couldn't do this one: \(reason)" }
        static let anAgent = "an agent"
        static let reasonNeedsLogin = "it needs you to sign in"
        static let reasonNoCaptions = "no captions on this video"
        static let reasonNotFound = "the video wasn't found"
        static let reasonBlocked = "the site blocked it"
        static let reasonFailed = "it didn't work"
        static let browserPermissionOff = "Your agent can use your browser to read pages when you allow it."
        static let allowBrowser = "Allow your agent to use your browser"
        static let browserPermissionOn = "Your agent may use your browser. Try again."

        // The honesty line: what the record is and is not.
        static let sawNoFrames = "An agent recorded that it watched this. Cicada saw no frames itself."
        static let legacyRecord = "Recorded before Cicada asked how it was read."
        static let readBySleep = "Read by Sleep."
        static let notReadBySleep = "Sleep hasn't read this yet."
        static let approximateWording = "Wording is approximate (a model's reading, not captions)."
        static func fromTheVideo(_ time: String?) -> String { time.map { t in "From the video · \(t)" } ?? "From the video" }
        static func recordedOn(_ day: String) -> String { day }

        // MARK: The reader's view of a watch record
        static func watchRecord(basis: VideoBasis?, engine: VideoEngine?) -> String {
            let how: String
            switch basis {
            case .transcript?: how = "from the video's transcript"
            case .frames?: how = "from the video's frames"
            case .both?: how = "from the video's frames and its transcript"
            case nil: how = "before Cicada asked how it was read"
            }
            let tail = engineTail(engine)
            return "A watch record: an agent recorded it \(how)\(tail). Cicada saw no frames itself."
        }
        /// What the agent said it did, reported plainly. `other` and absent say nothing.
        static func engineTail(_ engine: VideoEngine?) -> String {
            switch engine {
            case .captions?: ", from captions"
            case .videoLink?: ", reading the link directly"
            case .localFrames?: ", from frames it took itself"
            case .speechToText?: ", from speech-to-text"
            case .browser?: ", in a browser"
            case .other?, nil: ""
            }
        }
        static let approximateTurn = "approximate wording"
        static func mediaTurnMeta(time: String?, fidelity: VideoFidelity?) -> String {
            var parts = ["From the video"]
            if let time { parts.append(time) }
            if fidelity == .approximate { parts.append(approximateTurn) }
            return parts.joined(separator: " · ")
        }

        // MARK: The picker (Choose videos)
        static let tabUnread = "Not yet read"
        static let tabQueued = "Queued"
        static let tabRead = "Read"
        static let tabsLabel = "Which videos to show"
        static let picking = "Choosing"
        static func pickedCount(_ n: Int) -> String { "\(UsageFormat.count(n)) selected" }
        static func metadataSaved(_ day: String) -> String { "\(stateNone) · saved \(day)" }
        static let lengthUnknown = "length unknown"
        static let leaveChoosing = "Leave choosing"
        static let selectVideo = "Select this video"
        static let nothingHere = "Nothing here."
        static let nothingUnread = "Every saved video has been read, queued or watched."
        static let nothingQueued = "Nothing is in the queue."
        static let nothingRead = "Nothing has been read yet."

        // MARK: The run card
        static let runEyebrow = "Watch run"
        static let runEmptyTitle = "Pick videos to read or watch"
        static let runEmptyBody = "Tick them on the left. Each starts as a transcript, the light choice; switch one to Watch when the pictures matter."
        static let wantTranscriptName = "Transcript"
        static let wantWatchName = "Watch"
        static let wantTranscriptBlurb = "Captions or a transcript. Light, unless it runs past 3 hours."
        static let wantWatchBlurb = "Frames and the transcript. Medium up to 30 minutes; Heavy beyond, or when the length is unknown."
        static func selectAllUnread(_ n: Int) -> String { "Select all \(UsageFormat.count(n)) not read yet" }
        static func runTitle(_ n: Int) -> String { n == 1 ? "Read or watch 1 video" : "Read or watch \(UsageFormat.count(n)) videos" }
        static let copyForAgent = "Copy for an agent"
        static let copyForAgentHelp = "Queue these videos and copy a prompt to give your agent"
        static let copied = "Copied. Paste it into your agent."
        static let clearSelection = "Clear selection"
        static let sizeLabel = "Size"
        static let howLabel = "How"
        static let howAuto = "Let the agent choose"
        static let howCaptions = "Captions or transcript only"
        static let howLink = "Read the link directly"
        static let howLinkHelp = "Your agent may hand the link to a model that takes video. Nothing is downloaded."
        static let promptLabel = "What your agent gets"
        static let showAll = "Show all"
        static let showLess = "Show less"
        static let removeFromQueue = "Remove from the queue"
        static let notInQueueYet = "Not in the queue yet"
        static let itemMenuHelp = "What to ask for on this video"
        static let sizeLight = "Light"
        static let sizeMedium = "Medium"
        static let sizeHeavy = "Heavy"

        /// "3 light · 1 medium · 1 heavy (length unknown)" — words and known minutes only (ruling 12, G107): no price,
        /// no token, no estimate of how long a run will take.
        static func sizeLine(light: Int, medium: Int, heavy: Int, heavyUnknown: Int) -> String {
            var parts: [String] = []
            if light > 0 { parts.append("\(UsageFormat.count(light)) light") }
            if medium > 0 { parts.append("\(UsageFormat.count(medium)) medium") }
            if heavy > 0 {
                var text = "\(UsageFormat.count(heavy)) heavy"
                if heavyUnknown == heavy { text += " (length unknown)" }
                else if heavyUnknown > 0 { text += " (\(UsageFormat.count(heavyUnknown)) of unknown length)" }
                parts.append(text)
            }
            return parts.joined(separator: " · ")
        }
        /// "10 min to watch, plus 1 of unknown length" from the KNOWN lengths of the watch items only.
        static func minutesLine(minutes: Int, unknown: Int) -> String? {
            guard minutes > 0 || unknown > 0 else { return nil }
            var text = minutes > 0 ? "\(UsageFormat.count(minutes)) min to watch" : ""
            if unknown > 0 {
                let tail = "\(UsageFormat.count(unknown)) of unknown length"
                text = text.isEmpty ? "Watching \(tail)" : "\(text), plus \(tail)"
            }
            return text
        }

        // Progress
        static func startedAt(_ time: String) -> String { "\(runEyebrow) · started \(time)" }
        static func recordedOf(_ done: Int, _ total: Int) -> String { "\(UsageFormat.count(done)) of \(UsageFormat.count(total)) recorded" }
        static let whatYourAgentGot = "What your agent got"
        static let sleepReadsThese = "Sleep reads these the next time it runs."
        static let copyPromptAgain = "Copy the prompt again"
        static let copyPromptAgainHelp = "Copy the prompt for this run again"
        static let transcriptRead = "Transcript read"
        static let watchedWord = "Watched"
        static let recordedNoMethod = "Recorded, method not given"
        static let transcriptWord = "Transcript"
        static let watchWord = "Watch"
        static let watchedWithTranscript = "Watched, with transcript"
        static func couldntDoLine(want: VideoWant, reason: String) -> String {
            "\(want == .watch ? watchWord : transcriptWord) · couldn't do: \(reason)"
        }
        static func pickedUpByAgent(_ agent: String) -> String { "\(pickedUpByLead) \(agent)" }
        static let pickedUpByLead = "Picked up by"
        static let groupCouldntDo = "Couldn't do"
        static let groupPickedUp = "Picked up"
        static let groupWaiting = "Waiting"
        static let groupRecorded = "Recorded"
        static func group(_ title: String, _ n: Int) -> String { "\(title) · \(UsageFormat.count(n))" }
        static func recordedBy(_ agent: String, at time: String?) -> String {
            [agent, time].compactMap { $0 }.joined(separator: " · ")
        }
        static let backToRun = "Watch run"
        static let leaveRun = "Leave the run"
        static let meter = "Videos recorded"
        static func meterHelp(done: Int, total: Int) -> String { "\(UsageFormat.count(done)) of \(UsageFormat.count(total)) videos recorded" }

        // MARK: The hand-off's note
        static let leavesMacNote = "Cicada sends nothing. Your agent decides where a video goes."

        // MARK: Sleep's Details row
        static let sleepRowTitle = "Videos"
        static let sleepRowLink = "Choose videos ›"
        static let sleepRowLinkHelp = "Open the Feed's videos to choose what your agent reads"
        static func pickedUpSentence(_ n: Int) -> String {
            n == 1 ? "An agent has picked up 1 video." : "An agent has picked up \(UsageFormat.count(n)) videos."
        }

        // MARK: Failures
        static func loadFailed(_ error: any Error) -> String {
            if let api = error as? APIError, case .serverUnreachable = api {
                return "Cicada's backend isn't answering. It restarts on its own — try again in a moment."
            }
            return "Something went wrong reading your videos. Try again in a moment."
        }
        static let loadFailedTitle = "Couldn't load your videos"
        static let readingVideos = "Reading your videos…"

        /// A queue write that failed: the server's own sentence for a 422 (a full queue, a bad request), a plain line
        /// for anything else — a 400's or 404's detail names ids and is never shown.
        static func writeFailed(_ error: any Error) -> String {
            if let api = error as? APIError {
                switch api {
                case .httpError(422, let body):
                    if let sentence = detailSentence(body) { return sentence }
                case .serverUnreachable:
                    return "Cicada's backend isn't answering. It restarts on its own — try again in a moment."
                default: break
                }
            }
            return "Couldn't change the queue. Try again in a moment."
        }

        /// The `detail` of a FastAPI error body when it is one plain sentence.
        static func detailSentence(_ body: String) -> String? {
            guard let data = body.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let detail = object["detail"] as? String else { return nil }
            let line = detail.split(whereSeparator: \.isNewline).first.map(String.init)?.trimmingCharacters(in: .whitespaces) ?? ""
            return line.isEmpty || line.count > 200 ? nil : line
        }
    }
}
