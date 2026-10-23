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

    // MARK: Agents by provider umbrella (fix round 2026-10-22)

    private var providers: [ProviderUmbrella] {
        [ProviderUmbrella(id: "anthropic", label: "Anthropic", logo: "claude",
                          ways: [ProviderWay(id: "claude-code", label: "Claude Code", setup: ["claude-code"]),
                                 ProviderWay(id: "claude", label: "Claude app", setup: ["claude-desktop", "claude"])]),
         ProviderUmbrella(id: "openai", label: "OpenAI", logo: "openai",
                          ways: [ProviderWay(id: "codex", label: "Codex", setup: ["codex"]),
                                 ProviderWay(id: "chatgpt", label: "ChatGPT", setup: ["chatgpt"])]),
         ProviderUmbrella(id: "hermes", label: "Hermes", logo: "hermes",
                          ways: [ProviderWay(id: "hermes", label: "Hermes", setup: ["hermes"])])]
    }

    func testFoundProductsGroupUnderTheirProviderUmbrella() throws {
        let add = AgentWiringStep(step: "mcp", display: "claude mcp add cicada", argv: ["claude"], touches: [])
        let answer = AgentWiringResponse(agents: [wiring("claude-code", connect: [add]), wiring("codex"),
                                                  wiring("hermes")], python: "", repo: "", memory: "")
        let products = AgentStepRows.rows(wiring: answer, live: ["codex": AgentLiveRow(id: "codex", connected: true)],
                                          setups: ["hermes": try setup("hermes", prompt: "Add Cicada")],
                                          claudeAppInstalled: true)
        let rows = AgentStepRows.umbrellas(providers, products: products)
        XCTAssertEqual(rows.map(\.id), ["anthropic", "openai", "hermes"])
        XCTAssertEqual(rows[0].logo, "claude", "the umbrella's mark, never Claude Code's badge")
        XCTAssertEqual(rows[0].detail, "Claude Code · Claude app")
        XCTAssertEqual(rows[0].actionable.map(\.action), [.connect([add]), .setUpClaude],
                       "one Connect offers each product's own action")
        XCTAssertTrue(rows[1].connected)
        XCTAssertEqual(rows[1].detail, "Codex", "ChatGPT is not on this Mac, so it is not listed")
        XCTAssertTrue(rows[1].actionable.isEmpty)
        XCTAssertEqual(AgentStepRows.status(rows[1], started: []).on, true)
        XCTAssertEqual(AgentStepRows.status(rows[0], started: ["claude"]).word, Copy.Status.waiting)
        XCTAssertEqual(AgentStepRows.status(rows[2], started: []).word, Copy.agentsFound)
    }

    /// No product badge stands in for an umbrella, even before `/providers` answers.
    func testWithoutTheProvidersTableEachProductWearsItsVendorsMark() {
        let products = AgentStepRows.rows(wiring: AgentWiringResponse(agents: [wiring("claude-code"), wiring("codex")],
                                                                      python: "", repo: "", memory: ""),
                                          live: [:], setups: [:], claudeAppInstalled: false)
        let rows = AgentStepRows.umbrellas([], products: products)
        XCTAssertEqual(rows.map(\.logo), ["claude", "openai"])
        for row in rows { XCTAssertFalse(["claude-code", "codex"].contains(row.logo ?? ""), row.id) }
    }

    /// Item 2: no `claude-code` / `codex` mark anywhere in onboarding — only umbrella logos.
    func testOnboardingDrawsNoProductBadge() throws {
        for file in ["Views/Onboarding/AgentsStep.swift", "Views/Onboarding/OnboardingView.swift"] {
            let url = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(file) })
            let text = try String(contentsOf: url, encoding: .utf8)
            XCTAssertFalse(text.contains("entry.mark"), file)
            XCTAssertFalse(text.contains("AgentMark("), file)
        }
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

    func testATickTileSaysWhatItReadsAndItsConsentBeforeTheClick() {
        let entries = ImportCatalog.entries(ImportContext())
        let calendar = entries.first { $0.id == .app(AppSourceDrivers.calendar) }!
        XCTAssertEqual(SourceTiles.caption(calendar, needsAccess: false), Copy.importCalendarIdle)
        let browser = ImportEntry(id: .browser("safari"), category: .browsers, title: "Safari", origin: "safari",
                                  meta: "Bookmarks · History", idleLine: Copy.importTickToBringIn)
        XCTAssertEqual(SourceTiles.caption(browser, needsAccess: false), "Bookmarks · History",
                       "a generic idle line gives way to what it reads")
        XCTAssertEqual(SourceTiles.caption(browser, needsAccess: true), Copy.sourcesNeedsAccess)
        XCTAssertTrue(Copy.importNotesIdle.contains("macOS asks once"), "Apple Notes names its prompt")
    }

    func testHomesGettingStartedFoldsWhatOnboardingCovered() {
        let rows = [GettingStartedRow(id: .browser("chrome"), title: "Chrome", detail: "", state: .on),
                    GettingStartedRow(id: .agent("codex"), title: "Codex", detail: "", state: .working("…")),
                    GettingStartedRow(id: .app("calendar-local"), title: "Calendar", detail: "", state: .off)]
        let before = GettingStartedFold.of(rows: rows, onboarded: false, showsPastChats: true, showsAlsoFound: true)
        XCTAssertEqual(before.openRows.count, 3)
        XCTAssertEqual(before.covered, 0)
        XCTAssertTrue(before.showsPastChats && before.showsAlsoFound)
        let after = GettingStartedFold.of(rows: rows, onboarded: true, showsPastChats: true, showsAlsoFound: true)
        XCTAssertEqual(after.openRows.map(\.title), ["Calendar"], "only open rows stay")
        XCTAssertEqual(after.covered, 2)
        XCTAssertFalse(after.showsPastChats || after.showsAlsoFound, "never asked again")
        XCTAssertEqual(Copy.gsCoveredInSetup(2), "2 things already set up")
    }

    // MARK: Done

    private func honesty(_ mode: String, engine: String = "claude-cli") -> HonestyInputs {
        let preview = SleepEnginePreview(engine: engine, model: "", why: "")
        return HonestyInputs(schedule: ScheduleConfig(mode: mode, hour: 3, minute: 0),
                             preview: SleepEnginePreviews(manual: preview, scheduled: preview),
                             hasKey: false, ollamaReady: false, claudeConnected: true)
    }

    func testDoneSaysTonightAndNowOnlyWhenTrue() {
        func line(_ mode: String, brought: Bool, canRead: Bool = true, engine: String = "claude-cli") -> String {
            DoneLine.line(brought: brought, canReadNow: canRead, scheduleLoaded: true,
                          honesty: honesty(mode, engine: engine))
        }
        XCTAssertEqual(line("daily", brought: true),
                       "Talk to your agent; Cicada remembers. It reads tonight at 3:00, and now for what you brought in.")
        XCTAssertEqual(line("daily", brought: false), "Talk to your agent; Cicada remembers. It reads tonight at 3:00.")
        XCTAssertEqual(line("manual", brought: true),
                       "Talk to your agent; Cicada remembers. It reads what you brought in now.")
        XCTAssertEqual(line("manual", brought: false),
                       "Talk to your agent; Cicada remembers. Read now on Home builds your first pages.")
        XCTAssertEqual(line("daily", brought: true, canRead: false, engine: "none"),
                       "Talk to your agent; Cicada remembers. Read now on Home builds your first pages.",
                       "nothing can read: neither tonight nor now is promised")
        XCTAssertEqual(DoneLine.line(brought: false, canReadNow: true, scheduleLoaded: false, honesty: honesty("daily")),
                       Copy.doneLead, "unknown is never an answer")
        XCTAssertTrue(DoneLine.readsNow(brought: true, canReadNow: true))
        XCTAssertFalse(DoneLine.readsNow(brought: false, canReadNow: true), "nothing came in: no read")
        XCTAssertFalse(DoneLine.readsNow(brought: true, canReadNow: false))
    }

    /// Re-review 2026-10-22: a read started now on a key the person chose is said in words, with the provider's name.
    func testDoneNamesTheKeyANowReadBills() {
        let preview = SleepEnginePreview(engine: "litellm", model: "openai/gpt-x", why: "")
        let response = SleepEngineResponse(mode: "byok", model: "openai/gpt-x", disambiguationModel: "", source: "prefs",
                                           candidates: [],
                                           preview: SleepEnginePreviews(manual: preview, scheduled: preview),
                                           selected: "byok", provider: "openai",
                                           providers: [SleepEngineProvider(id: "openai", label: "OpenAI",
                                                                           connectionId: "byok-openai", hasKey: true,
                                                                           defaultModel: "openai/gpt-x", keyUrl: "")])
        XCTAssertEqual(DoneLine.nowKey(response), "OpenAI")
        XCTAssertEqual(DoneLine.tail(brought: true, canReadNow: true, scheduleLoaded: true,
                                     honesty: honesty("manual", engine: "litellm"), nowKey: "OpenAI"),
                       "It reads what you brought in now, on your OpenAI key.")
        XCTAssertNil(DoneLine.nowKey(self.response(selected: "auto", engine: "claude-cli")), "a plan is no key")
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
        let worm = words([Copy.MeetWorm.title, Copy.MeetWorm.subline, Copy.MeetWorm.number, Copy.MeetWorm.goesDown,
                          Copy.MeetWorm.example, Copy.onboardingBack, Copy.onboardingSkip, Copy.onboardingContinue])
        for (name, n) in [("welcome", welcome), ("intelligence", intelligence), ("sources", sources), ("worm", worm),
                          ("done", done)] {
            XCTAssertLessThan(n, 40, "\(name): \(n) words")
        }
    }
}
