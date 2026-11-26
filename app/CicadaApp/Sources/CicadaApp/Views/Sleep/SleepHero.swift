import SwiftUI

// MARK: - The hero readout (G125 v3, spec R-A4…R-A7)

/// The numeral the hero promotes — and `nil` when the state has none.
///
/// P8: `sleepDebtBracketText` is **re-composed** from this function and
/// `bracketTail`, never rewritten, so the twelve strings `SleepMoodTests`
/// asserts survive byte-for-byte. Two details the existing strings force,
/// read off the switch rather than guessed:
///
/// - `.curious`'s numeral comes from the CASE's associated value, not from
///   `debt` — `"[ 47 episodes behind ]"` is asserted with `debt: nil`.
/// - `.reading` is `debt?.unprocessedCount ?? 0` and therefore **never nil**:
///   `"[ 0 to read ]"` with a nil debt is an asserted string. The hero VIEW is
///   what decides not to draw a `0`; this function does not lie about it.
func heroCount(_ state: BookwormState, debt: SleepDebtView?) -> Int? {
    switch state {
    case .awake, .sleeping, .digesting, .happy, .error:
        return nil
    case .curious(let count):
        return count
    case .reading:
        return debt?.unprocessedCount ?? 0
    case .hungry:
        // A long gap with an empty queue is genuinely countless — the caption
        // says "overdue — hasn't consolidated in a while" and shows no
        // numeral, so neither does the hero.
        let count = debt?.unprocessedCount ?? 0
        return count > 0 ? count : nil
    }
}

/// The short chip beside the numeral (R-A4). Deliberately NOT `bracketTail`:
/// the tail is a caption phrase that carries the pluralised noun, the chip is
/// one or two words naming the state.
///
/// P9 — `first run` outranks `behind`/`overdue`: nothing has ever been
/// consolidated in this bank, so calling the queue a *backlog* would be
/// wrong. It needs a count to be about, so an empty queue with
/// `hasRunBefore == false` keeps its own word.
func heroQualifier(_ state: BookwormState, debt: SleepDebtView?) -> String {
    switch state {
    case .awake:
        return "awake"
    case .sleeping:
        return "sleeping"
    case .digesting:
        return "digesting"
    case .happy:
        return "caught up"
    case .error:
        return "failed"
    case .curious(let count):
        return firstRunWord(count: count, debt: debt) ?? "behind"
    case .reading:
        let count = debt?.unprocessedCount ?? 0
        // `intakeInFlight` holds `.reading` with an as-yet-unrefreshed queue
        // count of 0 (G125 R2) — nothing is behind, the worm is simply busy.
        guard count > 0 else { return "reading" }
        return firstRunWord(count: count, debt: debt) ?? "behind"
    case .hungry:
        let count = debt?.unprocessedCount ?? 0
        return firstRunWord(count: count, debt: debt) ?? "overdue"
    }
}

/// `"first run"` when Sleep has demonstrably never run in this bank and there
/// is a queue to describe; `nil` (fall through to the state's own word)
/// otherwise. A nil debt means "not loaded", never "has not run" — an unknown
/// must not be reported as a fact.
private func firstRunWord(count: Int, debt: SleepDebtView?) -> String? {
    (debt?.hasRunBefore == false && count > 0) ? "first run" : nil
}

/// The caption tail — everything the bracket line says after the numeral.
/// It owns the pluralisation, so it takes the same count `heroCount` returns.
func bracketTail(_ state: BookwormState, debt: SleepDebtView?) -> String {
    switch state {
    case .awake:
        return "awake"
    case .sleeping(let stage):
        return "sleeping · stage \(stage) of 5"
    case .digesting:
        return "digesting"
    case .happy:
        return "caught up"
    case .curious(let count):
        return "conversation\(count == 1 ? "" : "s") behind"
    case .reading:
        return "to read"
    case .hungry:
        let count = debt?.unprocessedCount ?? 0
        guard count > 0 else { return "overdue — hasn't consolidated in a while" }
        return "conversation\(count == 1 ? "" : "s") behind — overdue"
    case .error:
        return "last cycle failed"
    }
}

// MARK: - The meter (R-A5)

/// **The bar never renders without its noun.** One bar with two exclusive
/// meanings and never a bare `%`:
///
/// - idle → `Rested 12%` from `debt.restedPct`, and **nothing at all** when
///   `restedPct == nil` (no baseline: Sleep has never run in this bank, and a
///   fabricated 100% would be a lie);
/// - running → `Read 138 of 203`, where both numbers are the sums of
///   `resolveOriginCounts`'s `readByOrigin`/`queueByOrigin` — already
///   resolved ONCE per body evaluation (H1) — so the label's two numbers and
///   the bar's fraction come from one reading. Deliberately **not**
///   `progressPct`, which is a different scalar on a different cadence and
///   would let the words and the fill disagree (P7).
///
/// A running cycle past Stage 1 has no per-episode unit at all
/// (`sleep_cycle.progress_pct` returns `None`), so `total == 0` draws no bar
/// rather than `Read 0 of 0` — the run object is the running instrument.
enum HeroMeter: Equatable {
    case rested(pct: Int)
    case reading(read: Int, total: Int)

    /// The reference's segmented bar: 24 whole blocks, never a fractional one.
    static let blockCount = 24

    var label: String {
        switch self {
        case .rested(let pct): "Rested \(pct)%"
        case .reading(let read, let total): "Read \(read) of \(total)"
        }
    }

    /// Clamped to `0...1`: a backend that reports a rested percentage above
    /// 100 (or a read count past its own total) is a bug, and the bar must
    /// not overflow its 24 blocks because of it. The LABEL still shows the
    /// raw numbers — the honest reading is the one worth seeing.
    var fraction: Double {
        switch self {
        case .rested(let pct):
            return min(1, max(0, Double(pct) / 100))
        case .reading(let read, let total):
            guard total > 0 else { return 0 }
            return min(1, max(0, Double(read) / Double(total)))
        }
    }

    var filledBlocks: Int {
        min(Self.blockCount, max(0, Int((fraction * Double(Self.blockCount)).rounded())))
    }

    /// DESIGN_RULES §10 (Sleep): "'Rested 0%' becomes a sentence instead of 26 empty boxes" (R-HS15).
    /// The noun stays first (R-A5); the rest says what the number means from facts the page already
    /// holds — the queue's count and the mood — never a guess. The volume/age split stays on hover
    /// (`heroMeterHelp`).
    func sentence(unprocessed: Int, mood: BookwormState) -> String {
        switch self {
        case .reading(let read, let total):
            return "Read \(UsageFormat.count(read)) of \(UsageFormat.count(total)) so far."
        case .rested(let pct):
            if unprocessed == 0 { return "Fully rested — nothing is waiting." }
            // Looks pass 2 (2026-10-23): a hungry room's headline already says "N to read — overdue." above this
            // readout, so the sentence says what the number is made of instead of saying "overdue" again (DR-38).
            return "Rested \(pct)% — based on how much is waiting, and for how long."
        }
    }
}

func heroMeter(mood: BookwormState, debt: SleepDebtView?, read: Int, total: Int) -> HeroMeter? {
    if case .sleeping = mood {
        guard total > 0 else { return nil }
        return .reading(read: read, total: total)
    }
    guard let pct = debt?.restedPct else { return nil }
    return .rested(pct: pct)
}

/// The breakdown behind `Rested n%` — hover text on the meter's label, and
/// `nil` (no tooltip at all) for everything else.
///
/// Round-2 live check, R-A5: the page drew `Rested n%` in the hero's labelled
/// meter AND again two rows below it as `Rested n% — volume v%, age a%`. One
/// number on screen twice is exactly what this page refuses; the duplicate
/// line is gone and its one piece of extra information — which of the two
/// ratios the backend combined is doing the work — moved here, where a
/// breakdown belongs.
///
/// `.reading` gets nothing: `Read a of b` already shows both of its numbers,
/// so there is nothing left to explain, and inventing a tooltip for it would
/// put a second meaning on the same hover.
func heroMeterHelp(_ meter: HeroMeter, debt: SleepDebtView?) -> String? {
    guard case .rested = meter, let debt else { return nil }
    return Copy.restedBreakdown(volumePct: debt.volumePct, agePct: debt.agePct)
}

// MARK: - The one control (R-A7, Track Z §4.2)

/// The page's ONE Consolidate/Cancel control (R-A7, G125 R10). While a cycle
/// runs the one control IS Cancel — the disabled "Consolidating…" twin pill is
/// gone (design §4.2). `FixWaveTests` pins `sleepVM.triggerManually()` to this
/// file.
///
/// `consolidateEnabled` and `queuedCount` come from `SleepPageModel`, the one
/// reading the sentence above it also drew from, so the button can never be
/// live while the sentence says there is nothing to read.
///
/// Beside it sits the engine label, which names what a cycle you start would run (R-HS8). While a run reads nothing
/// is captioned under the pair (2026-11-26): what a stop does while it files is the run object's note, what Cancel
/// does is its tooltip, and the engine a run keeps is the engine label's tooltip. Idle, one line says what arrived
/// since the last run started.
struct SleepControlRow: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store

    let consolidateEnabled: Bool
    let queuedCount: Int
    /// Sleep page v5 — the page's own reading (`SleepPageModel`), for Pause / Continue / End this run, the elapsed
    /// time, the Reading options link and the arrivals reason. `nil` keeps the pre-v5 row.
    var page: SleepPageModel? = nil
    /// ROR-118 — set on the leading edge beside the room's rectangle (round 5: the engine and Options are DR-40 neutral
    /// buttons beside the one primary, so they read as controls); the offscreen layouts keep the centred group.
    var leading = false
    /// ROR-118 round 6 - which part of the row is drawn: beside the room the buttons sit inside the block that is the
    /// room's height, and the lines that explain them (the stop's whisper, the elapsed time) hang under the pair, so
    /// a state with more to say never makes the block taller than the room.
    enum Part { case all, buttons, captions }
    var part: Part = .all
    /// The room's interaction state: the run bar's schedule opens the lamp's popover through it. Only the page's
    /// leading layout (the bar) needs it.
    var room: RoomModel? = nil

    @State private var optionsOpen = false

    /// The page's own reading when there is one (H1: the control never disagrees with the sentence and the run object
    /// above and below it — the live capture showed Cancel under a stage that only a drain reaches).
    private var draining: Bool { (page?.drain ?? sleepVM.status?.drain)?.active == true }
    private var paused: SleepPausedRun? { page?.paused }
    /// The last stage is filing: a stop now waits for the commit.
    private var filing: Bool {
        sleepVM.isRunning && page?.runningStage == SleepStages.all.count
    }

    var body: some View {
        VStack(alignment: leading ? .leading : .center, spacing: CicadaTheme.spacingSM) {
            if part != .captions {
                // Beside the room (the page's layout) the row is the run bar; the centred group below is the
                // offscreen layout the at-rest and run-strip tests lay out.
                if leading, let room, let page { runBar(page: page, room: room) } else { buttonRow }
            }
            if part != .buttons { captions }
        }
        .padding(.top, part == .captions && hasCaptions ? CicadaTheme.spacingSM : 0)
        .frame(maxWidth: .infinity, alignment: leading ? .leading : .center)
        .sheet(isPresented: $optionsOpen) {
            ReadingOptionsSheet(waiting: page?.readable ?? queuedCount,
                                onClose: { optionsOpen = false },
                                onConsolidate: {
                                    optionsOpen = false
                                    Task {
                                        await sleepVM.triggerManually()
                                        await store.refresh([.status, .channels])
                                    }
                                })
        }
    }

    /// The page's one run bar (`SleepRunBar.swift` holds its quiet parts): what will run, when, and the go button in
    /// one soft block. A narrow column drops words in order — the engine to its model, then the schedule to its
    /// moon and switch — and never the primary.
    private func runBar(page: SleepPageModel, room: RoomModel) -> some View {
        ViewThatFits(in: .horizontal) {
            ForEach(RunBarLevel.allCases, id: \.self) { level in barContent(page: page, room: room, level: level) }
        }
        .softCard(shape: .block, inset: .snug, fillsWidth: true)
    }

    private func barContent(page: SleepPageModel, room: RoomModel, level: RunBarLevel) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            // The owner's quick switch (R-HS8, R-HS9). It stays while a cycle runs: a change applies to the next one
            // (G80). It names the person's own engine and model — never another.
            RunBarEngine(short: level.engineIsShort)
            RunBarSchedule(page: page, room: room, glyphOnly: !level.schedule)
            if showsOptionsLink { optionsButton }
            Spacer(minLength: CicadaTheme.spacingSM)
            if paused != nil, !sleepVM.isRunning {
                TextButton(title: Copy.SleepV5.endRun, help: Copy.SleepV5.endRunHelp) {
                    Task { await sleepVM.endRun() }
                }
            }
            primaryButton(short: level.primaryIsShort)
        }
    }

    /// Options opens the reading options (how often a run saves, what it runs on): a slider mark, said in `.help`.
    private var optionsButton: some View {
        IconButton(systemName: "slider.horizontal.3", help: Copy.SleepV5.optionsHelp,
                   accessibilityLabel: Copy.SleepV5.optionsShort) { optionsOpen = true }
    }

    /// The row's one primary: Pause or Cancel while a cycle runs, Continue while one waits paused, else Consolidate.
    @ViewBuilder
    private func primaryButton(short: Bool) -> some View {
        if sleepVM.isRunning {
            if draining { pauseButton } else { cancelButton }
        } else if let paused {
            continueButton(paused)
        } else {
            consolidateButton(short: short)
        }
    }

    private var buttonRow: some View {
            HStack(spacing: CicadaTheme.spacingSM) {
                primaryButton(short: false)
                // The owner's quick switch (R-HS8, R-HS9). It stays while a cycle runs: a change
                // applies to the next one (G80). It names the person's own engine and model — never another.
                EngineLabelButton(size: .compact)   // D6: a label that opens Settings → Intelligence (UI-A)
                // The owner's at-rest row (2026-10-16): Consolidate · engine · Options, one height. Options opens the
                // same reading options the floating "Reading options…" link did, on this row instead of its own line.
                if showsOptionsLink {
                    NeutralButton(title: Copy.SleepV5.options, size: .compact,
                                  help: Copy.SleepV5.optionsHelp) { optionsOpen = true }
                }
                if paused != nil, !sleepVM.isRunning {
                    TextButton(title: Copy.SleepV5.endRun, help: Copy.SleepV5.endRunHelp) {
                        Task { await sleepVM.endRun() }
                    }
                }
            }
    }

    private var hasCaptions: Bool { caption != nil }

    @ViewBuilder
    private var captions: some View {
        if let caption {
            Text(caption)
                .font(CicadaTheme.captionFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(leading ? .leading : .center)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Idle after a run that left arrivals: the reason Consolidate is live again. Nothing while a run reads — the run's
    /// object (`RunLine`) says what is true of it, and the stop's words are tooltips.
    private var caption: String? {
        if !sleepVM.isRunning, paused == nil, consolidateEnabled,
           let arrived = page?.drain?.arrivedSince, arrived > 0, page?.drain?.finished == true {
            return Copy.SleepV5.newSinceYouStarted(arrived)
        }
        return nil
    }

    /// Options sits in the row while nothing reads and nothing is paused (A5, A10; owner 2026-10-16).
    private var showsOptionsLink: Bool {
        guard let page, !sleepVM.isRunning, page.paused == nil else { return false }
        return (page.readable ?? queuedCount) > 0
    }

    /// The page's one prominent action (R-M5, Z-B14): `.glassProminent`,
    /// accent-tinted, on macOS 26 and `.borderedProminent` before, through the
    /// shared `PrimaryActionButton` so its ink follows the key-window rule. It
    /// lifts on hover because it is the one thing on the page that starts
    /// something; Cancel beside it stays quiet.
    private func consolidateButton(short: Bool = false) -> some View {
        PrimaryActionButton(title: short ? Copy.SleepPage.consolidateShort : Copy.consolidateNow, systemImage: "moon.fill") {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        }
        .font(CicadaTheme.font(size: 12, weight: .semibold))
        .controlSize(.large)
        .disabled(!consolidateEnabled)
        .hoverLift()
        .help(queuedCount == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }

    /// Sleep page v5 — the paused run's one primary (DR-40): Continue, named for the engine it will run on (a
    /// scheduled run's Continue runs on the manual engine, which can be a plan — ruling 16). Disabled only while a
    /// weekly limit's reset is still ahead.
    private func continueButton(_ paused: SleepPausedRun) -> some View {
        let engine = SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview)?.manual.engine
        let waits = page?.continueWaitsForReset ?? false
        return PrimaryActionButton(title: Copy.SleepV5.continueRun, systemImage: "play.fill") {
            Task {
                await sleepVM.continueRun()
                await store.refresh([.status, .channels])
            }
        }
        .font(CicadaTheme.font(size: 12, weight: .semibold))
        .controlSize(.large)
        .disabled(!paused.canContinue || waits)
        .hoverLift()
        .help(waits ? (page?.resetWhen.map(Copy.SleepV5.resetsThenContinue) ?? Copy.SleepV5.continueWhenItResets)
                    : engine.map { Copy.SleepV5.continueHelp(Copy.engineLabel($0)) } ?? Copy.SleepV5.continueHelpGeneric)
        .accessibilityLabel(Copy.SleepV5.continueRun)
    }

    /// Sleep page v5 — while a run reads in batches the one control is Pause: it stops at the next safe point, keeps
    /// what is filed and leaves a paused run to continue (the cancel path, recorded as a pause by the server).
    private var pauseButton: some View {
        Button {
            Task { await sleepVM.pause() }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isCancelling {
                    ProgressView().controlSize(.small).frame(width: 10, height: 10)
                } else {
                    Image(systemName: "pause.fill").font(CicadaTheme.font(size: 10, weight: .semibold))
                }
                Text(sleepVM.isCancelling ? Copy.SleepV5.pausing : Copy.SleepV5.pause)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surfaceElevated)
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isCancelling)
        .help(filing ? Copy.SleepV5.filingWhisper : Copy.SleepV5.pauseHelp)
        .accessibilityLabel(sleepVM.isCancelling ? Copy.SleepV5.pausing : Copy.SleepV5.pause)
    }

    /// Only shown while a cycle is running, and then INSTEAD of Consolidate
    /// (design §4.2): the one control is Cancel for as long as there is a
    /// cycle to stop. Cooperative, not instant — the long
    /// `Copy.cancelSleepExplainer` is its tooltip (the one-line caption beside it retired 2026-11-26).
    private var cancelButton: some View {
        Button {
            Task { await sleepVM.cancel() }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isCancelling {
                    ProgressView().controlSize(.small).frame(width: 10, height: 10)
                } else {
                    Image(systemName: "xmark").font(CicadaTheme.font(size: 10, weight: .semibold))
                }
                Text(sleepVM.isCancelling ? Copy.cancellingSleep : Copy.cancelSleep)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surfaceElevated)
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isCancelling)
        .help(filing ? Copy.SleepV5.filingWhisper
                     : draining ? Copy.cancelDrainExplainer : Copy.cancelSleepExplainer)
        .accessibilityLabel(Copy.cancelSleep)
    }
}

/// The engine a line names, with its real mark (round-3 brief: "use logos
/// whenever possible"; Z-P26; DR-52). `claude-cli` IS Claude Code, so it borrows that
/// origin's mark; a key wears its provider's (owner 2026-11-24: "with the logos of providers"), read from the model
/// it runs (`ContributorIdentity.modelMark`) — the key glyph only when the provider is truly unknown.
struct EngineMark: View {
    let engine: String
    var size: CGFloat = 14
    /// R-AG12 / DR-52 — the preview's model, so a key run through OpenRouter wears OpenRouter's
    /// mark (the button names OpenRouter; the key glyph would contradict it).
    var model: String? = nil

    /// Which mark an engine wears (R-HS13): the Claude plan runs Claude Code's own binary, the ChatGPT
    /// plan wears its card's mark (`EngineOption.previewMark`), Ollama its own, and an API key the mark of the
    /// provider whose model it runs, a key only when that is unknown. `codex-cli` drew the key before DS-3b (DR-52).
    enum Source: Equatable {
        case origin(String)
        case logo(String)
        case symbol(String)
    }

    static func source(for engine: String, model: String? = nil) -> Source {
        switch engine {
        case "claude-cli": .origin("claude-code")
        case "codex-cli": EngineOption.previewMark(engine: engine).map(Source.logo) ?? .symbol("key")
        case "ollama": .logo("ollama")
        case "litellm" where EngineOption.runsOnOpenRouter(model):
            EngineOption.previewMark(engine: engine, model: model).map(Source.logo) ?? .symbol("key")
        // G49/G50: the person's own signed-in tool (`cursor-cli`, `opencode-cli`, `grok-cli`) wears that tool's mark
        // from the shared set; only a key run has no vendor to show.
        case _ where engine.hasSuffix("-cli") && LogoSet.umbrellaMarks.contains(String(engine.dropLast(4))):
            .logo(String(engine.dropLast(4)))
        default: model.flatMap { ContributorIdentity.modelMark(author: $0) }.map(Source.logo) ?? .symbol("key")
        }
    }

    var body: some View {
        switch Self.source(for: engine, model: model) {
        case .origin(let origin):
            OriginMark(origin: origin, size: size)
        case .logo(let name):
            LogoImage(name: name, size: size)
        case .symbol(let name):
            Image(systemName: name)
                .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: size, height: size)
        }
    }
}
