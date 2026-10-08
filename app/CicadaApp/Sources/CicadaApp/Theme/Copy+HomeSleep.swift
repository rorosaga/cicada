import Foundation

/// Direction D, part 3b (DS-3b): the Sleep page's quick engine menu, Details, the Settings sheets
/// and the ⌘K Settings rows. Their own file for Track I's R-IA19 reason — sibling tracks append to
/// `Copy.swift`, and one file per track means two tracks never edit the same lines. Plain words, no
/// "!", no bare "%" (DR-59); no price or token count except `SleepUsage`'s, which is the one place the
/// 2026-09-28 ruling allows them. `HomeSleepCopyTests` holds every string in `homeSleepLabels` to that,
/// and `SleepUsage`'s figures are asserted in `CycleUsageTextTests`.
extension Copy {
    /// The owner's quick switch (2026-09-23; R-HS7…R-HS11).
    enum EngineMenu {
        static let title = "Engine for the cycles you start"
        /// `sleep_engine_prefs.env_pin_sentence`'s words: the environment, not this menu, sets the engine.
        static func pinnedByEnvironment(_ mode: String) -> String {
            "CICADA_LLM_MODE=\(mode) in Cicada's environment (api/.env) sets the engine, so a choice here changes "
                + "nothing. Remove that line and restart Cicada to choose here."
        }
        static let buttonHelp = "Engine and model for the cycles you start"
        static func buttonAccessibility(_ label: String) -> String { "\(title): \(label)" }
        static let model = "Model"
        static let howAutoPicks = "How Auto picks"
        /// R-HS11 — the one pair of preview labels, app-wide (the menu, Settings → Engines,
        /// Settings → Sleep). Three places said it two ways before.
        static let whenYouStart = "When you start a cycle"
        static let scheduledCycles = "Scheduled cycles"
        static let writeFailed = "Couldn't change the engine — nothing changed."
        static let moreInSettings = "More in Settings → Engines ›"
        static let plansAndKeys = "Plans & keys ›"
        static let autoPrefix = "Auto"
        static func signInFirst(_ label: String) -> String { "Sign in on Plans & keys to use your \(label)" }
        /// A run resolves its engine once and keeps it; a change made while it reads waits (never names an engine).
        static let runKeepsEngine = "This run keeps the engine it started with. Your choice applies when a run starts or continues."
    }

    /// What a cycle cost (2026-09-28 ruling, TODO ruling 12): the Sleep page's Details and its engine
    /// menu, nowhere else. Every figure states its basis in words — "charged", "at list price", or a
    /// plan window's share — and a plan's share carries the honest limit that it covers all use.
    enum SleepUsage {
        static let notRecorded = "Usage not recorded"
        static let noCalls = "No model calls"
        static let ranLocally = "Ran on this Mac"
        static let modelsTitle = "Models"
        static let lastCycleTitle = "What it cost"
        /// Under a run of several batches the newest history commit is one batch (G163): say so.
        static let lastBatchTitle = "What the last batch cost"
        static let tokensNotReported = "tokens not reported"
        static let planNote =
            "The plan's percentage covers all your use of it, so this change can include things you did meanwhile."
        /// The visible half of `planNote` on a one-line row, where a hover alone would hide the limit.
        static let planCoversAll = "covers all your use of the plan"
        static let windowRolledOver = "window reset meanwhile"
        static let firstSeenNote =
            "Claude reports a window only after a call, so the first figure is the reading after the cycle's first call."
        static let windowReset = "Window has reset since it was read"
        static let perMillionNote = "Prices are per million tokens: input / output."

        static func source(connection: String?, engine: String?) -> String? {
            switch connection {
            case "claude-plan": return "Claude plan"
            case "chatgpt-plan": return "ChatGPT plan"
            case "ollama-local": return "Ollama"
            case "byok-openrouter": return "OpenRouter"
            case .some(let c) where c.hasPrefix("byok"): return "API key"
            default: break
            }
            switch engine {
            case "claude-cli": return "Claude plan"
            case "codex-cli": return "ChatGPT plan"
            case "ollama": return "Ollama"
            case "litellm": return "API key"
            default: return nil
            }
        }

        /// A plan window in the words the plan itself uses. `primary`/`secondary` are ChatGPT's own
        /// two windows, whose lengths the backend does not state, so they are not given one here.
        static func window(_ id: String) -> String {
            switch id {
            case "five_hour": "5-hour window"
            case "seven_day": "weekly window"
            case "seven_day_opus": "weekly Opus window"
            case "seven_day_sonnet": "weekly Sonnet window"
            case "primary": "main window"
            case "secondary": "second window"
            case "fullest": "busiest window"
            default: "usage window"
            }
        }

        static func charged(_ amount: String, on source: String?) -> String {
            source.map { "\(amount) charged · \($0)" } ?? "\(amount) charged"
        }
        static func atListPrice(_ amount: String) -> String { "about \(amount) at list price" }
        static func chargedTotal(_ amount: String) -> String { "\(amount) charged" }
        static func calls(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) call\(n == 1 ? "" : "s")"
        }
        static func failed(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) failed"
        }
        static func tokensIn(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) tokens in"
        }
        static func tokensOut(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) tokens out"
        }
        static func lastCycle(_ amount: String) -> String { "Last cycle: \(amount) charged" }
        static func asOf(_ relative: String) -> String { "as of \(relative)" }
        static func resets(_ when: String) -> String { "resets \(when)" }
    }

    /// Details (R-HS15): Last cycle's rows, the readout's keys, and the untitled episode.
    enum SleepDetailsWords {
        /// Owner 2026-10-05 — a click on a queued row copies what Sleep would read, and says what it copied.
        static func copied(_ kind: String?) -> String {
            switch kind {
            case "conversation": "Conversation ID copied"
            case "link": "Link copied"
            case "links": "Links copied"
            case "path": "Path copied"
            default: "Episode ID copied"
            }
        }
        /// The row's tooltip and VoiceOver hint: what a click copies.
        static func copyHint(_ kind: String?) -> String {
            switch kind {
            case "conversation": "Click to copy the conversation ID"
            case "link": "Click to copy the link"
            case "links": "Click to copy the tab links"
            case "path": "Click to copy the file path"
            default: "Click to copy the episode ID"
            }
        }
        static let failedTitle = "Sleep cycle error"
        static let cancelledTitle = "Cancelled"
        static let cancelledText = "Stopped cleanly before any writes — nothing was lost."
        /// A stopped person-started run (G163): earlier batches are filed and stay so; the batch that was
        /// still reading is dropped and read again next time, so this never says "nothing was lost".
        static func cancelledDrainText(filed: Int, frozen: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "Stopped at a safe point — \(UsageFormat.count(filed, locale: locale)) of \(UsageFormat.count(frozen, locale: locale)) filed stay filed; the rest wait for the next Consolidate."
        }
        /// Nothing was filed yet: the batch that was reading is dropped, so its reads are paid again.
        static func cancelledDrainNoneText() -> String {
            "Stopped — nothing was filed; the batch being read is dropped and read again next time."
        }
        /// Last cycle's row for a run that read everything waiting, in batches — only a run that finished.
        static let drainTitle = "Read everything"
        /// A run that stopped before it read everything: how much stays filed, never a batch count
        /// (the wire's `batches` is the plan, and a dropped batch is counted in `batch`).
        static let stoppedTitle = "Where it stopped"
        static func stoppedText(filed: Int, frozen: Int, locale: Locale = .autoupdatingCurrent) -> String {
            guard filed > 0 else { return "Nothing was filed; the batch being read is dropped and read again next time." }
            let count = { (n: Int) in UsageFormat.count(n, locale: locale) }
            return "\(count(filed)) of \(count(frozen)) filed stay filed; the rest wait for the next Consolidate."
        }
        static func drainText(filed: Int, frozen: Int, batches: Int, requeued: Int,
                              locale: Locale = .autoupdatingCurrent) -> String {
            let count = { (n: Int) in UsageFormat.count(n, locale: locale) }
            var text = "\(count(filed)) of \(count(frozen)) filed · \(count(batches)) \(batches == 1 ? "batch" : "batches")"
            if requeued > 0 { text += " · \(count(requeued)) will be read next time" }
            return text
        }
        static let pausedTitle = "Paused at your plan's limit"
        static let pausedFallback = "The rest wait for the next Consolidate."
        static func capTitle(_ cap: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "Episode cap reached (\(UsageFormat.count(cap, locale: locale)))"
        }
        static func capText(processed: Int, queued: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(processed, locale: locale)) of \(UsageFormat.count(queued, locale: locale)) processed — the rest stay queued for the next cycle."
        }
        static let warningTitle = "Completed with warnings"
        static let inMemory = "In memory"
        static let feedingIt = "Feeding it"
        static let lastCycleTook = "Last cycle took"
        static let lastBatchTook = "Last batch took"
        static let lastEngine = "Last engine"
        /// The engine row's dash reason. Not "Sleep hasn't run": `lastEngine` is also nil while the
        /// status is still loading and on an older backend, and a dash's reason is never a guess (R-A14).
        static let noEngineYet = "No cycle has reported its engine yet."
        static let untitled = "Untitled"
    }

    /// The add-folder and Manage sheets (the owner's report; R-HS17).
    enum Folders {
        static let addTitle = "Add a folder"
        static let name = "Name"
        static let project = "Project"
        static let projectHelp = "Notes from this folder are kept under this project."
        static let writtenByAnAgent = "Written by an agent"
        static let writtenByAnAgentHelp =
            "Research an agent wrote for you is kept and searchable, but never counted as your own words."
        static func filesIn(_ folder: String) -> String { "Files in \(folder) (and its subfolders)" }
        /// Renders a saved rule verbatim — the one place a glob can appear, and only if the person
        /// typed one before DS-3b (R-HS17: a round trip never drops a rule).
        static func filesMatching(_ rule: String) -> String { "Files matching \(rule)" }
        static let noSubfolders = "No subfolders here — everything in this folder counts as yours."
        /// A folder watched from another Mac (G133 `paths:`): its subfolders can't be listed here.
        static let notOnThisMac =
            "This folder isn't on this Mac — open Manage on the Mac that has it to add a subfolder."
        static let chooseSubfolder = "Choose a subfolder…"
        static func pickInside(_ folder: String) -> String { "Pick a folder inside \(folder)." }
        static let manageHelp = "Changing this re-reads the folder so every file is credited to the right author."
    }
    /// A Settings sheet's close × (R-HS16).
    static let sheetClose = "Close"

    /// A Settings row's detail line in ⌘K — "Settings · Engines" — so a row reads where it lives
    /// before ⏎ opens it there (R-HS19).
    enum PaletteSettings {
        static func detail(_ section: String) -> String { "\(Copy.settings) · \(section)" }
    }

    /// Every DS-3b label `HomeSleepCopyTests` holds to DR-59. Later tasks append here.
    static let homeSleepLabels: [String] = [
        EngineMenu.title, EngineMenu.buttonHelp, EngineMenu.model, EngineMenu.howAutoPicks,
        EngineMenu.whenYouStart, EngineMenu.scheduledCycles, EngineMenu.writeFailed, EngineMenu.moreInSettings,
        EngineMenu.plansAndKeys, EngineMenu.signInFirst("ChatGPT plan"),
        // `capText` is a sentence that passes 60 characters once its counts have four digits, so it
        // stays off this list (Task 3).
        SleepDetailsWords.failedTitle, SleepDetailsWords.cancelledTitle, SleepDetailsWords.cancelledText,
        SleepDetailsWords.drainTitle, SleepDetailsWords.stoppedTitle, SleepDetailsWords.lastBatchTook,
        SleepDetailsWords.pausedTitle, SleepUsage.lastBatchTitle,
        SleepDetailsWords.capTitle(2), SleepDetailsWords.warningTitle, SleepDetailsWords.inMemory,
        SleepDetailsWords.feedingIt, SleepDetailsWords.lastCycleTook, SleepDetailsWords.lastEngine,
        SleepDetailsWords.noEngineYet, SleepDetailsWords.untitled,
        SleepUsage.notRecorded, SleepUsage.noCalls, SleepUsage.ranLocally, SleepUsage.modelsTitle,
        SleepUsage.lastCycleTitle, SleepUsage.windowReset,
        // `writtenByAnAgentHelp`, `noSubfolders`, `notOnThisMac` and `manageHelp` are sentences over 60 characters,
        // so they stay off this list (Task 4).
        Folders.addTitle, Folders.name, Folders.project, Folders.projectHelp, Folders.writtenByAnAgent,
        Folders.filesIn("research"), Folders.filesMatching("*.draft.md"), Folders.chooseSubfolder,
        Folders.pickInside("example-notes"), sheetClose,
        PaletteSettings.detail("Engines"),
    ]
}
