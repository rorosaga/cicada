import XCTest
@testable import CicadaApp

/// Settings defaults, pass 2 (owner 2026-10-22: "Let's just work towards the good defaults"). Engines opens on Auto —
/// what it uses now and why, in words — with the other engines under one fold; Plans & keys says each card's state
/// in words; a value Cicada's setup fixes says where it is changed (a docs link, never a variable); and a fresh memory
/// is never said to be "set up on another Mac".
final class SettingsDefaultsPassTwoTests: XCTestCase {
    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    private var repoRoot: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    }

    private func candidate(_ id: String, label: String, available: Bool = true, connected: Bool = true,
                           detail: String? = nil) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: label, available: available, connected: connected, models: [], detail: detail)
    }

    private var candidates: [SleepEngineCandidate] {
        [candidate("auto", label: "Auto"), candidate("agent", label: "Claude plan"),
         candidate("codex", label: "ChatGPT plan", connected: false), candidate("openrouter", label: "OpenRouter", connected: false),
         candidate("local", label: "Ollama", available: false, connected: false), candidate("byok", label: "API key")]
    }

    private func response(selected: String, engine: String, source: String = "prefs") -> SleepEngineResponse {
        let preview = SleepEnginePreview(engine: engine, model: "", why: "")
        return SleepEngineResponse(mode: selected == "openrouter" ? "byok" : selected, model: "", disambiguationModel: "",
                                   source: source, candidates: candidates,
                                   preview: SleepEnginePreviews(manual: preview, scheduled: preview), selected: selected)
    }

    // MARK: Engines — Auto first

    func testAutoSaysWhatItUsesNowAndWhy() {
        let plan = EngineHeadline.of(response(selected: "auto", engine: "claude-cli"))
        XCTAssertEqual(plan.title, "Auto")
        XCTAssertEqual(plan.line, "Using your Claude plan — you're signed in.")
        XCTAssertEqual(plan.mark, "agent")
        XCTAssertTrue(plan.isAuto)
        XCTAssertFalse(plan.needsSignIn)

        XCTAssertEqual(EngineHeadline.of(response(selected: "auto", engine: "codex-cli")).line,
                       "Using your ChatGPT plan — you're signed in.")
        XCTAssertEqual(EngineHeadline.of(response(selected: "auto", engine: "ollama")).line,
                       "Using Ollama on this Mac — no plan is signed in.")
        let none = EngineHeadline.of(response(selected: "auto", engine: "none"))
        XCTAssertTrue(none.needsSignIn, "nothing to read with: the line points at signing in")
        XCTAssertEqual(none.line, Copy.EngineHeadline.nothingYet)
        XCTAssertNil(EngineHeadline.backToAuto(response(selected: "auto", engine: "claude-cli")))
    }

    func testAStoredChoiceIsShownWithBackToAuto() {
        let chosen = response(selected: "codex", engine: "codex-cli")
        let headline = EngineHeadline.of(chosen)
        XCTAssertEqual(headline.title, "ChatGPT plan", "the person's choice, by its card's own name")
        XCTAssertFalse(headline.isAuto)
        XCTAssertTrue(headline.line.contains(Copy.costModelPlan))
        XCTAssertEqual(EngineHeadline.backToAuto(chosen), EngineWrite(mode: "auto", model: nil),
                       "Back to Auto writes Auto with no model — each engine runs its own default")
        XCTAssertNil(EngineHeadline.backToAuto(response(selected: "agent", engine: "claude-cli", source: "env")),
                     "the environment fixes the engine: a write would change nothing")
        XCTAssertEqual(EngineHeadline.of(response(selected: "openrouter", engine: "litellm")).title, "OpenRouter")
    }

    /// Ruling 31: Auto with no engine reads with nothing, so nothing leaves the Mac — never "your key sends…".
    func testAutoWithNoEngineSaysNothingLeaves() {
        for engine in ["none", "auto"] {
            XCTAssertNil(LeavesMacNote.text(selected: "auto", provider: nil, manualEngine: engine, providers: []), engine)
        }
        XCTAssertNotNil(LeavesMacNote.text(selected: "auto", provider: nil, manualEngine: "claude-cli", providers: []))
    }

    func testTheFoldHoldsEveryOtherEngine() {
        XCTAssertEqual(EngineHeadline.otherCandidates(candidates).map(\.id),
                       ["agent", "codex", "openrouter", "local", "byok"])
    }

    func testSettingsFoldsAndOnboardingKeepsTheFullRow() throws {
        XCTAssertTrue(try source("Sources/CicadaApp/Views/Onboarding/WhoReadsPage.swift").contains("EngineChooser()"),
                      "onboarding's Who reads is the choice itself (F-05): every card stays on show")
        let chooser = try source("Sources/CicadaApp/Views/Settings/EngineChooser.swift")
        XCTAssertTrue(chooser.contains("@AppStorage(EngineChooser.othersOpenKey)"), "DR-39: remembered per viewer")
        XCTAssertEqual(EngineChooser.othersOpenKey, "cicada.engines.othersOpen")
        XCTAssertNotEqual(EngineChooser.othersOpenKey, ConnectionsView.keysOpenKey)
        XCTAssertTrue(chooser.contains("Copy.EngineHeadline.differentEngine"))
        XCTAssertTrue(chooser.contains("Copy.EngineHeadline.backToAuto"))
        // Every trust control the page had is still drawn outside the fold.
        for needle in ["overageToggle(response)", "previewSection(preview)", "leavesMacNote(for: response)",
                       "connectionStep(for: candidate)", "pinnedNote(response)"] {
            XCTAssertTrue(chooser.contains(needle), needle)
        }
    }

    func testTheEnginesSubtitleIsPlainAndProviderNeutral() {
        let subtitle = Copy.enginesSubtitle.lowercased()
        for word in ["model", "claude", "chatgpt", "openai", "anthropic", "ollama", "openrouter", "llm"] {
            XCTAssertFalse(subtitle.contains(word), "the subtitle names \(word)")
        }
    }

    func testASearchForAnotherEngineStillLandsOnTheChoice() {
        let all = SettingsIndex.staticEntries + SettingsIndex.pageEntries
        for query in ["different engine", "back to auto"] {
            XCTAssertTrue(SettingsIndex.search(query, in: all).prefix(3).map(\.entry.id).contains(.engineChoice), query)
        }
        // D6: a provider's name finds the plans and keys it signs in with.
        XCTAssertTrue(SettingsIndex.search("openrouter", in: all).prefix(3).map(\.entry.id).contains(.plansAndKeys))
    }

    // MARK: Plans & keys, in words

    private func connection(_ id: String, mode: String?, connected: Bool, available: Bool = true,
                            detail: String? = nil, how: String? = nil) throws -> ConnectionStatus {
        var fields: [String: Any] = ["id": id, "label": id, "kind": "x", "connected": connected, "available": available]
        if let mode { fields["login"] = ["mode": mode] }
        if let detail { fields["detail"] = detail }
        if let how { fields["how"] = how }
        return try JSONDecoder().decode(ConnectionStatus.self, from: JSONSerialization.data(withJSONObject: fields))
    }

    /// The backend's own sentences, as `cicada engine list` prints them (real shapes, synthetic values).
    func testNoCardSaysAnAddressACommandOrAPath() throws {
        let cards = [
            try connection("claude-plan", mode: "terminal", connected: true,
                           how: "Signed in to Claude Code on this machine as `verify@example.invalid`. When Sleep or Ask runs on your Claude plan it goes through the `claude` CLI — Cicada never sees your token. This Mac's environment sets ANTHROPIC_API_KEY, which would take Claude Code off your Claude plan."),
            try connection("claude-plan", mode: "terminal", connected: false,
                           detail: "Not signed in — Connect opens Terminal with `claude auth login`."),
            try connection("chatgpt-plan", mode: "device-code", connected: true,
                           how: "Signed in to ChatGPT with Cicada's own Codex sign-in on this Mac — separate from Codex in your terminal. When Sleep or Ask runs on your ChatGPT plan it goes through `codex exec`; Cicada never sees your token."),
            try connection("ollama-local", mode: "none", connected: false, available: false,
                           detail: "Ollama not reachable at http://localhost:11434 (All connection attempts failed). Install from ollama.com and start it."),
            try connection("ollama-local", mode: "none", connected: false, detail: "Model not pulled — run `ollama pull llama3.1`"),
            try connection("ollama-local", mode: "none", connected: true, how: "Local models at `http://localhost:11434` — free."),
            try connection("byok-anthropic", mode: "key", connected: true,
                           how: "Key stored in /Users/someone/.cicada/secrets.env (0600); billed per token by Anthropic."),
            try connection("byok-openrouter", mode: "oauth", connected: false,
                           detail: "Sign in with OpenRouter, or paste a key; it is stored in /Users/someone/.cicada/secrets.env (0600)."),
        ]
        for card in cards {
            for line in [ConnectionsView.howLine(card), ConnectionsView.unconnectedDetail(card)].compactMap({ $0 }) {
                for needle in ["`", "localhost", "11434", "CLI", "0600", "secrets.env", "/Users/", "_API_KEY", "codex exec"] {
                    XCTAssertFalse(line.contains(needle), "\(card.id): \"\(line)\" says \(needle)")
                }
            }
        }
        XCTAssertEqual(ConnectionsView.howLine(cards[0]), Copy.ConnectionLine.claudeSignedIn)
        XCTAssertEqual(ConnectionsView.unconnectedDetail(cards[1]), Copy.ConnectionLine.claudeSignedOut)
        XCTAssertEqual(ConnectionsView.unconnectedDetail(cards[3]), Copy.ConnectionLine.localNotRunning)
        XCTAssertEqual(ConnectionsView.howLine(cards[6]), Copy.ConnectionLine.keySaved)
    }

    /// The signed-out sentence is recognised by its opening words; this holds the app's reading to the backend's.
    func testTheClaudeSignedOutSentenceStillOpensTheWayTheAppReadsIt() throws {
        let adapter = try String(contentsOf: repoRoot.appendingPathComponent("api/services/connections/claude_cli.py"),
                                 encoding: .utf8)
        XCTAssertTrue(adapter.contains("detail=\"Not signed in — Connect opens Terminal"))
    }

    /// An install hint or an API-key-instead-of-a-plan sentence names its own fix; those keep the backend's words.
    func testAnInstallHintKeepsTheBackendsSentence() throws {
        let hint = "Install Claude Code, then sign in."
        let card = try connection("claude-plan", mode: "terminal", connected: false, available: false, detail: hint)
        XCTAssertEqual(ConnectionsView.unconnectedDetail(card), hint)
    }

    func testTheEngineCardsStateLineIsInWords() {
        XCTAssertEqual(EngineOption.stateLine(for: candidate("local", label: "Ollama", available: false, connected: false,
                                                             detail: "Ollama not reachable at http://localhost:11434")),
                       Copy.ConnectionLine.localNotRunning)
        XCTAssertEqual(EngineOption.stateLine(for: candidate("agent", label: "Claude plan", connected: false,
                                                             detail: "Not signed in — Connect opens Terminal with `claude auth login`.")),
                       Copy.ConnectionLine.claudeSignedOut)
        XCTAssertFalse(Copy.sleepEngineExplainer.contains("`"), "the plan switch's explainer names no command")
    }

    // MARK: What the setup fixes says where it is changed

    func testEveryFixedValueLinksTheDocsPageThatSaysHow() throws {
        XCTAssertTrue(try source("Sources/CicadaApp/Views/Settings/EngineChooser.swift")
            .contains("SettingsHelpLink(url: Copy.SettingsHelp.engineFixed)"))
        XCTAssertTrue(try source("Sources/CicadaApp/Views/Settings/DevicesSettingsView.swift")
            .contains("SettingsHelpLink(url: Copy.SettingsHelp.serverFixed)"))
        XCTAssertTrue(try source("Sources/CicadaApp/Views/Settings/PrivacyView.swift")
            .contains("SettingsHelpLink(url: Copy.SettingsHelp.usageLedger"))
        let doc = try String(contentsOf: repoRoot.appendingPathComponent("docs/settings-outside-the-app.md"), encoding: .utf8)
        // GitHub's anchor for each heading the links name.
        let anchors = doc.components(separatedBy: .newlines).filter { $0.hasPrefix("## ") }.map {
            "#" + $0.dropFirst(3).lowercased().replacingOccurrences(of: " ", with: "-")
        }
        for url in [Copy.SettingsHelp.engineFixed, Copy.SettingsHelp.serverFixed, Copy.SettingsHelp.usageLedger] {
            XCTAssertEqual(url.scheme, "https")
            XCTAssertTrue(url.absoluteString.hasPrefix(Copy.SettingsHelp.page))
            XCTAssertTrue(anchors.contains("#" + (url.fragment ?? "")), "\(url) names no heading in the docs page")
        }
        XCTAssertTrue(Copy.SettingsHelp.page.hasSuffix("docs/settings-outside-the-app.md"))
        XCTAssertEqual(Copy.SettingsHelp.usageLedgerLink(off: false), "How to turn it off")
        XCTAssertEqual(Copy.SettingsHelp.usageLedgerLink(off: true), "How to turn it on")
    }

    // MARK: A fresh memory is not "set up on another Mac" (B-model)

    private static let small = "intfloat/multilingual-e5-small"
    private static let sharper = "google/embeddinggemma-2:768"
    private static let large = "google/embeddinggemma-300m"

    private func status(recorded: String??, sharperOffered: Bool = true) -> EmbeddingsStatus {
        var models = [EmbeddingModelOption(id: Self.small, label: "Built in", needsDownload: false, available: false),
                      EmbeddingModelOption(id: Self.large, label: "Larger", needsDownload: true, needsToken: true,
                                           available: false)]
        if sharperOffered {
            models.insert(EmbeddingModelOption(id: Self.sharper, label: "Sharper", needsDownload: true, needsToken: false,
                                               available: false, downloadBytes: 585_000_000), at: 0)
        }
        return EmbeddingsStatus(model: Self.large, nextModel: Self.large, release: false, models: models,
                                recorded: recorded)
    }

    func testAFreshMemoryOffersTheSharperVersionWithoutBlamingAnotherMac() {
        let row = SearchUnderstanding.meaning(status(recorded: .some(nil)), sleeping: false)
        XCTAssertEqual(row?.detail, Copy.SearchFiles.meaningNotYet(bytes: 585_000_000))
        XCTAssertFalse(row?.detail.contains("another Mac") ?? true)
        XCTAssertEqual(row?.action, .fetchMeaning(Self.sharper))
        XCTAssertEqual(row?.button, Copy.SearchFiles.turnOn)
        let noSharper = SearchUnderstanding.meaning(status(recorded: .some(nil), sharperOffered: false), sleeping: false)
        XCTAssertEqual(noSharper?.detail, Copy.SearchFiles.meaningWordsOnly)
    }

    func testAMemoryBuiltElsewhereStillSaysSo() {
        XCTAssertEqual(SearchUnderstanding.meaning(status(recorded: .some(Self.large)), sleeping: false)?.detail,
                       Copy.SearchFiles.meaningMissingLarger)
        XCTAssertEqual(SearchUnderstanding.meaning(status(recorded: .none), sleeping: false)?.detail,
                       Copy.SearchFiles.meaningMissingLarger, "an older backend that doesn't say: as before")
    }

    func testTheWireTellsNothingRecordedFromAnOlderBackend() throws {
        let fresh = try JSONDecoder().decode(EmbeddingsStatus.self,
                                             from: Data(#"{"model":"m","nextModel":"m","recorded":null}"#.utf8))
        XCTAssertTrue(fresh.nothingBuiltYet)
        let built = try JSONDecoder().decode(EmbeddingsStatus.self,
                                             from: Data(#"{"model":"m","nextModel":"m","recorded":"m"}"#.utf8))
        XCTAssertFalse(built.nothingBuiltYet)
        let older = try JSONDecoder().decode(EmbeddingsStatus.self, from: Data(#"{"model":"m","nextModel":"m"}"#.utf8))
        XCTAssertFalse(older.nothingBuiltYet)
    }
}
