import XCTest
@testable import CicadaApp

/// Onboarding v2 (G217, G92, ruling 36; 2026-10-22) — what each working step shows, as data.
@MainActor
final class OnboardingStepsTests: XCTestCase {
    // MARK: Intelligence (ruling 36 D1)

    private func response(selected: String, engine: String) -> SleepEngineResponse {
        let candidates = [
            SleepEngineCandidate(id: "auto", label: "Auto", available: true, connected: true, models: [], detail: nil),
            SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true, models: [], detail: nil),
            SleepEngineCandidate(id: "codex", label: "ChatGPT plan", available: true, connected: true, models: [], detail: nil),
            SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true, models: [], detail: nil),
        ]
        let preview = SleepEnginePreview(engine: engine, model: "", why: "")
        return SleepEngineResponse(mode: selected, model: "", disambiguationModel: "", source: "prefs",
                                   candidates: candidates,
                                   preview: SleepEnginePreviews(manual: preview, scheduled: preview), selected: selected)
    }

    func testASignedInPlanIsPreselectedAndSaysWhatRuns() {
        XCTAssertEqual(IntelligenceStepState.of(response(selected: "auto", engine: "claude-cli")),
                       .plan(line: "Using your Claude plan — you're signed in.",
                             runs: "Cicada runs your own Claude Code on your plan.", mark: "claude"))
        XCTAssertEqual(IntelligenceStepState.of(response(selected: "auto", engine: "codex-cli")),
                       .plan(line: "Using your ChatGPT plan — you're signed in.",
                             runs: "Cicada runs your own Codex on your plan.", mark: "openai"))
    }

    func testNothingToReadWithShowsPlansAndKeysAsEquals() {
        XCTAssertEqual(IntelligenceStepState.of(nil), .nothing, "unknown is never a plan")
        XCTAssertEqual(IntelligenceStepState.of(response(selected: "auto", engine: "none")), .nothing)
    }

    func testAChosenPlanReadsAsThePlanAndAKeyByItsOwnName() {
        XCTAssertEqual(IntelligenceStepState.of(response(selected: "codex", engine: "codex-cli")),
                       .plan(line: "Using your ChatGPT plan — you're signed in.",
                             runs: "Cicada runs your own Codex on your plan.", mark: "openai"))
        guard case let .chosen(title, _, _) = IntelligenceStepState.of(response(selected: "byok", engine: "litellm"))
        else { return XCTFail("a chosen key is shown by its own words") }
        XCTAssertEqual(title, "API key")
    }

    // MARK: Agents

    private func wiring(_ id: String, installed: Bool = true, recall: String = "off", autosave: String = "off",
                        connect: [AgentWiringStep] = [], autorecall: String = "n/a",
                        autorecallOn: [AgentWiringStep] = []) -> AgentWiring {
        AgentWiring(id: id, installed: installed, binary: installed ? "/bin/\(id)" : nil, recall: recall,
                    autosave: autosave, connect: connect, detail: nil, autorecall: autorecall, autorecallOn: autorecallOn)
    }

    private func setup(_ harness: String, prompt: String) throws -> AgentSetupPrompt {
        let json = #"{"harness": "\#(harness)", "kind": "prompt", "title": "t", "prompt": "\#(prompt)", "argv": [], "display": []}"#
        return try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(json.utf8))
    }

    func testOnlyAgentsFoundOnThisMachineAreRowsInCatalogOrder() throws {
        let add = AgentWiringStep(step: "mcp", display: "claude mcp add cicada", argv: ["claude"], touches: [])
        let recall = AgentWiringStep(step: "recall", display: "recall on", argv: ["claude"], touches: [])
        let answer = AgentWiringResponse(agents: [
            wiring("codex", recall: "on", autosave: "on"),
            wiring("claude-code", connect: [add], autorecall: "off", autorecallOn: [recall]),
            wiring("opencode", installed: false),
            wiring("hermes"),
        ], python: "", repo: "", memory: "")
        let rows = AgentStepRows.rows(wiring: answer, live: ["codex": AgentLiveRow(id: "codex", connected: true)],
                                      setups: ["hermes": try setup("hermes", prompt: "Add Cicada")],
                                      claudeAppInstalled: false)
        XCTAssertEqual(rows.map(\.id), ["claude-code", "codex", "hermes"], "OpenCode is not installed; the Claude app is absent")
        XCTAssertEqual(rows[0].action, .connect([add, recall]), "Connect for me plus Remembers automatically (R-OB12)")
        XCTAssertEqual(rows[1].action, .none, "already calling Cicada")
        XCTAssertTrue(rows[1].connected)
        XCTAssertEqual(rows[2].action, .copy("Add Cicada"))
        XCTAssertEqual(AgentStepRows.status(rows[1], started: false).on, true)
        XCTAssertEqual(AgentStepRows.status(rows[0], started: false).word, Copy.agentsFound)
        XCTAssertEqual(AgentStepRows.status(rows[0], started: true).word, Copy.Status.waiting)
    }

    /// The plugin is the canonical Claude Code door: a plugin-wired Claude Code answers no argv, so nothing is run.
    func testAPluginWiredClaudeCodeIsOfferedNothingToRun() {
        let plugin = AgentWiring(id: "claude-code", installed: true, binary: "/bin/claude", recall: "on", autosave: "on",
                                 connect: [], detail: nil, autorecall: "on", capabilities: ["via": "plugin"])
        let action = AgentStepRows.action(for: AgentCatalog.entry(for: "claude-code")!, wiring: plugin, setups: [:])
        XCTAssertEqual(action, .preparing)
    }

    func testTheClaudeAppIsARowWhenInstalledAndCloudAgentsNever() {
        let rows = AgentStepRows.rows(wiring: AgentWiringResponse(agents: [], python: "", repo: "", memory: ""),
                                      live: [:], setups: [:], claudeAppInstalled: true)
        XCTAssertEqual(rows.map(\.id), ["claude"])
        XCTAssertEqual(rows[0].action, .setUpClaude)
        let cloud = AgentStepRows.rows(wiring: nil, live: ["grok": AgentLiveRow(id: "grok", connected: true)],
                                       setups: [:], claudeAppInstalled: false)
        XCTAssertTrue(cloud.isEmpty, "cloud agents reach Cicada through the step's own rows below the list")
    }

    // MARK: Sources

    func testTheGridHoldsThePopularSourcesInOrder() {
        let imports = ImportCatalog.entries(ImportContext())
        let tiles = SourceTiles.tiles(imports: imports)
        XCTAssertEqual(tiles.map(\.title), ["Calendar", Copy.contactsTitle, "Messages", "YouTube", "X", "Instagram",
                                            Copy.sourcesChats])
        XCTAssertFalse(tiles.contains { $0.title == Copy.importNotes }, "Apple Notes stays on the Sources page")
        if case .tick(let entry) = tiles[0].kind {
            XCTAssertEqual(entry.id, .app(AppSourceDrivers.calendar))
        } else { XCTFail("Calendar ticks through the one turn-on") }
        if case .open(let entry) = tiles[2].kind { XCTAssertEqual(entry.id, "imessage") } else { XCTFail() }
        XCTAssertEqual(tiles.last?.kind, .chats)
    }

    func testATileSaysOneWord() {
        XCTAssertEqual(SourceTiles.status(phase: nil).word, Copy.sourcesOff)
        XCTAssertEqual(SourceTiles.status(phase: .comingIn).word, Copy.sourcesComingIn)
        XCTAssertEqual(SourceTiles.status(phase: .done).word, Copy.sourcesOn)
        XCTAssertEqual(SourceTiles.status(phase: .needsYou).tone, .attention)
        XCTAssertEqual(SourceTiles.status(catalog: .connected).word, Copy.sourcesOn)
        XCTAssertEqual(SourceTiles.chatsStatus(phases: []).word, Copy.sourcesDropFile)
        XCTAssertEqual(SourceTiles.chatsStatus(phases: [.done, .comingIn]).word, Copy.sourcesComingIn)
        let calendar = ImportCatalog.entries(ImportContext()).first { $0.id == .app(AppSourceDrivers.calendar) }!
        XCTAssertFalse(SourceTiles.isTicked(calendar, phase: nil), "never ticked for the person (R-OB6)")
        XCTAssertTrue(SourceTiles.isTicked(calendar, phase: .comingIn))
        XCTAssertFalse(SourceTiles.isTicked(calendar, phase: .needsYou), "its tick is the Allow…")
    }

    // MARK: Done

    private func honesty(_ mode: String, engine: String = "claude-cli") -> HonestyInputs {
        let preview = SleepEnginePreview(engine: engine, model: "", why: "")
        return HonestyInputs(schedule: ScheduleConfig(mode: mode, hour: 3, minute: 0),
                             preview: SleepEnginePreviews(manual: preview, scheduled: preview),
                             hasKey: false, ollamaReady: false, claudeConnected: true)
    }

    func testDoneNeverPromisesTonightOnAManualSchedule() {
        XCTAssertEqual(DoneLine.line(importsComingIn: false, scheduleLoaded: true, honesty: honesty("manual")),
                       "Talk to your agent; Cicada remembers. Read now on Home builds your first pages.")
        XCTAssertEqual(DoneLine.line(importsComingIn: false, scheduleLoaded: true, honesty: honesty("daily")),
                       "Talk to your agent; Cicada remembers. It consolidates tonight at 3:00.")
        XCTAssertEqual(DoneLine.line(importsComingIn: true, scheduleLoaded: true, honesty: honesty("daily")),
                       "Talk to your agent; Cicada remembers. Your imports are coming in now.")
        XCTAssertEqual(DoneLine.line(importsComingIn: false, scheduleLoaded: false, honesty: honesty("daily")),
                       Copy.doneLead, "unknown is never an answer")
        XCTAssertEqual(DoneLine.tail(importsComingIn: false, scheduleLoaded: true,
                                     honesty: honesty("daily", engine: "none")), Copy.doneReadNow,
                       "a schedule nothing can read is not a promise")
    }

    // MARK: Words (the brief's bar: under 40 words a step; Agents and Sources add one name per row or tile)

    func testEachStepsFixedWordsStayUnderForty() {
        func words(_ parts: [String]) -> Int {
            // A word has a letter: "—" and a step number are not words.
            parts.joined(separator: " ").split { $0.isWhitespace }.filter { $0.contains { $0.isLetter } }.count
        }
        let welcome = words([Copy.welcomeHello("Verify"), Copy.welcomeLine, Copy.welcomeNotYou("Verify"),
                             Copy.onboardingContinue, Copy.welcomeTryTheDemo, Copy.welcomeSetUpLater])
        let frame = [Copy.onboardingStepOf(2), Copy.welcomeSetUpLater, Copy.onboardingBack, Copy.onboardingSkip,
                     Copy.onboardingContinue]
        let intelligence = words(frame + [Copy.intelTitle, Copy.intelSubline,
                                          "Using your Claude plan — you're signed in.", Copy.intelRuns("Claude Code"),
                                          Copy.intelUseKey])
        let sources = words(frame + [Copy.importTitle, Copy.sourcesSubline, Copy.sourcesHowToExport])
        let done = words([Copy.readyTitle, Copy.doneLead, Copy.doneReadNow, Copy.onboardingBack,
                          Copy.onboardingOpenCicada])
        for (name, n) in [("welcome", welcome), ("intelligence", intelligence), ("sources", sources), ("done", done)] {
            XCTAssertLessThan(n, 40, "\(name): \(n) words")
        }
    }
}
