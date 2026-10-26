import AppKit
import XCTest
@testable import CicadaApp

// Onboarding v3 (2026-10-24, after HeyClicky): permissions as a designed flow, a live first agent call, Done ending on
// the person's own memory, the real menu-bar worm in the show, fewer words, and every way out. Everything here runs on
// fakes: no System Settings, no permission read, no relaunch, no network.

private final class V3Probe: TracePermissionProbe, @unchecked Sendable {
    var answers: [TracePermission: Bool] = [:]
    private(set) var asked: [TracePermission] = []
    func granted(_ permission: TracePermission) -> Bool {
        asked.append(permission)
        return answers[permission] ?? false
    }
}

@MainActor
private final class V3Opener: PermissionSettingsOpener {
    private(set) var opened: [URL] = []
    func open(_ url: URL) { opened.append(url) }
}

@MainActor
private final class V3Clock: PermissionPollClock {
    private(set) var tick: (@MainActor () -> Void)?
    private(set) var started = 0
    private(set) var cancelled = 0

    final class Token: PermissionPollToken {
        let onCancel: () -> Void
        init(onCancel: @escaping () -> Void) { self.onCancel = onCancel }
        func cancel() { onCancel() }
    }

    func every(_ interval: TimeInterval, _ tick: @escaping @MainActor () -> Void) -> PermissionPollToken {
        started += 1
        self.tick = tick
        return Token { [weak self] in self?.cancelled += 1; self?.tick = nil }
    }

    func fire() { tick?() }
}

@MainActor
private final class V3Relauncher: AppRelauncher {
    private(set) var relaunched: [PermissionResume] = []
    func relaunch(resume: PermissionResume) { relaunched.append(resume) }
}

// MARK: - 1. Permissions

@MainActor
final class OnboardingV3PermissionTests: XCTestCase {
    private var defaults: UserDefaults!
    private let suite = "OnboardingV3PermissionTests"

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private func make(_ kind: TracePermission, place: PermissionPlace = .sources, relaunch: Bool = true)
        -> (PermissionDragHelperModel, V3Probe, V3Opener, V3Clock, V3Relauncher) {
        let probe = V3Probe()
        let opener = V3Opener()
        let clock = V3Clock()
        let relauncher = V3Relauncher()
        let model = PermissionDragHelperModel(kind: kind, probe: probe, opener: opener, clock: clock, place: place,
                                              memory: PermissionMemory(defaults: defaults),
                                              relauncher: relaunch ? relauncher : nil,
                                              now: { Date(timeIntervalSince1970: 1_800_000_000) })
        return (model, probe, opener, clock, relauncher)
    }

    func testDragMeInWhenCicadaIsNotInTheList() {
        for kind in TracePermission.allCases {
            let (model, _, _, _, _) = make(kind)
            model.start()
            XCTAssertEqual(model.ask, .drag, "\(kind)")
            XCTAssertEqual(model.need, Copy.Traces.need(kind))
            XCTAssertTrue(model.need.contains("Drag me into"))
        }
    }

    func testFlipMyToggleOnOnceCicadaHasBeenSeenInTheList() {
        PermissionMemory(defaults: defaults).noteGranted(.fullDiskAccess)
        let (model, _, _, _, _) = make(.fullDiskAccess)
        model.start()
        XCTAssertEqual(model.ask, .flip, "seen granted before, refused now: its switch is off")
        XCTAssertEqual(model.need, "I'm already in the Full Disk Access list. Flip my toggle on.")
        let (other, _, _, _, _) = make(.screenRecording)
        XCTAssertEqual(other.ask, .drag, "the memory is per list")
    }

    func testAGrantIsRememberedSoTheNextAskIsTheToggle() {
        let (model, probe, _, clock, _) = make(.accessibility)
        model.start()
        model.open()
        probe.answers[.accessibility] = true
        clock.fire()
        XCTAssertEqual(model.phase, .granted)
        XCTAssertTrue(PermissionMemory(defaults: defaults).inList(.accessibility))
        let (later, _, _, _, _) = make(.accessibility)
        XCTAssertEqual(later.ask, .flip)
    }

    func testBackFromSettingsWithoutAGrantMovesTheWordsOn() {
        let (ax, _, _, _, _) = make(.accessibility)
        ax.start()
        ax.returned()
        XCTAssertEqual(ax.ask, .drag, "coming back before Open says nothing new")
        ax.open()
        ax.returned()
        XCTAssertEqual(ax.ask, .flip, "Accessibility applies at once: no relaunch, the toggle")
        XCTAssertEqual(ax.phase, .opened, "still asking")

        for kind in [TracePermission.screenRecording, .fullDiskAccess] {
            let (model, _, _, _, _) = make(kind)
            model.start()
            model.open()
            XCTAssertTrue(model.offersReopen, "\(kind): Already on? Reopen Cicada, quietly, once Settings is open")
            model.returned()
            XCTAssertEqual(model.ask, .reopen, "\(kind): the preflight can stay false until Cicada reopens")
            XCTAssertEqual(model.need, "Already on? Reopen Cicada to apply it.")
        }
    }

    func testBackFromSettingsWithAGrantTicksAtOnce() {
        let (model, probe, _, clock, _) = make(.screenRecording)
        var ticks = 0
        model.onGranted = { ticks += 1 }
        model.start()
        model.open()
        probe.answers[.screenRecording] = true
        model.returned()
        XCTAssertEqual(model.phase, .granted)
        XCTAssertEqual(ticks, 1)
        XCTAssertEqual(clock.cancelled, 1)
    }

    func testReopenLeavesAMarkerForTheSameStepAndStopsThePoll() {
        let (model, _, _, clock, relauncher) = make(.screenRecording, place: .traces)
        model.start()
        model.open()
        model.returned()
        model.reopen()
        XCTAssertEqual(relauncher.relaunched,
                       [PermissionResume(kind: .screenRecording, place: .traces, at: Date(timeIntervalSince1970: 1_800_000_000))])
        XCTAssertEqual(clock.cancelled, 1)
    }

    func testAccessibilityNeverOffersAReopenAndNoRelauncherMeansNoReopen() {
        let (ax, _, _, _, _) = make(.accessibility)
        ax.start()
        ax.open()
        XCTAssertFalse(ax.offersReopen)
        let (bare, _, _, _, relauncher) = make(.fullDiskAccess, relaunch: false)
        bare.start()
        bare.open()
        XCTAssertFalse(bare.offersReopen)
        bare.reopen()
        XCTAssertTrue(relauncher.relaunched.isEmpty)
    }

    /// Only ever a preflight: across start, the poll, a return and a reopen the probe's one question is asked, and the
    /// opener is used only by the person's Open.
    func testEveryLookIsAPreflightAndOnlyOpenOpensSettings() {
        let (model, probe, opener, clock, _) = make(.fullDiskAccess)
        model.start()
        clock.fire()
        XCTAssertTrue(opener.opened.isEmpty, "the poll never opens anything")
        model.open()
        clock.fire()
        model.returned()
        XCTAssertEqual(probe.asked, [.fullDiskAccess, .fullDiskAccess, .fullDiskAccess, .fullDiskAccess])
        XCTAssertEqual(opener.opened.map(\.absoluteString),
                       ["x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
        XCTAssertEqual(clock.started, 1, "one gentle poll")
    }

    func testAClosedHelperTurnsTheRowIntoAnOpenLink() {
        XCTAssertEqual(PermissionRowState.after(nil, granted: false), .ask)
        XCTAssertEqual(PermissionRowState.after(.asking, granted: false), .ask)
        XCTAssertEqual(PermissionRowState.after(.opened, granted: false), .ask)
        XCTAssertEqual(PermissionRowState.after(.cancelled, granted: false), .retry)
        XCTAssertEqual(PermissionRowState.after(.granted, granted: false), .granted)
        XCTAssertEqual(PermissionRowState.after(.cancelled, granted: true), .granted)
    }

    func testTheResumeMarkerRoundTripsAndIsReadOnceByTheRightCaller() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let marker = PermissionResume(kind: .fullDiskAccess, place: .onboarding(browser: "safari"), at: now)
        XCTAssertEqual(PermissionResume.decode(marker.encoded), marker)
        marker.save(defaults)
        XCTAssertNil(PermissionResume.take(matching: { !$0.isOnboarding }, now: now, defaults: defaults),
                     "the app shell leaves onboarding's marker alone")
        XCTAssertNotNil(defaults.string(forKey: PermissionResume.defaultsKey))
        XCTAssertEqual(PermissionResume.take(matching: \.isOnboarding, now: now.addingTimeInterval(30), defaults: defaults),
                       marker)
        XCTAssertNil(defaults.string(forKey: PermissionResume.defaultsKey), "read once")

        PermissionResume(kind: .screenRecording, place: .traces, at: now).save(defaults)
        XCTAssertNil(PermissionResume.take(matching: { _ in true }, now: now.addingTimeInterval(PermissionResume.maxAge + 1),
                                           defaults: defaults), "a stale marker is dropped unread")
        XCTAssertNil(defaults.string(forKey: PermissionResume.defaultsKey))
        defaults.set("someday|nowhere|x", forKey: PermissionResume.defaultsKey)
        XCTAssertNil(PermissionResume.take(matching: { _ in true }, defaults: defaults))
        XCTAssertNil(defaults.string(forKey: PermissionResume.defaultsKey), "a value no build wrote never traps")
        for place in [PermissionPlace.traces, .sources, .onboarding(browser: nil), .onboarding(browser: "safari")] {
            XCTAssertEqual(PermissionPlace(word: place.word), place)
        }
    }

    /// Review blocker 2: a rerun's marker reopens the rerun; a first run's reopens through the gate, or through the
    /// shell when the gate will not raise it.
    func testReopenComesBackToSourcesOnAFirstRunAndOnARerun() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let first = PermissionResume(kind: .fullDiskAccess, place: .onboarding(browser: "safari"), at: now)
        let rerun = PermissionResume(kind: .fullDiskAccess, place: .onboardingRerun(browser: "safari"), at: now)
        XCTAssertEqual(PermissionResume.decode(rerun.encoded), rerun)
        XCTAssertEqual(PermissionPlace(word: "rerun"), .onboardingRerun(browser: nil))
        XCTAssertTrue(rerun.place.isOnboarding && rerun.place.isRerun)
        XCTAssertEqual(rerun.place.browser, "safari")
        XCTAssertEqual(first.place.browser, "safari")

        XCTAssertNil(PermissionResume.reopensOnboarding(first, gateShows: true),
                     "a first run: the gate raises onboarding, which takes the marker")
        XCTAssertEqual(PermissionResume.reopensOnboarding(first, gateShows: false), .firstRun,
                       "a first run whose memory already has pages: the shell raises it")
        XCTAssertEqual(PermissionResume.reopensOnboarding(rerun, gateShows: false), .rerun,
                       "a rerun's bank keeps its pages: the shell reopens the rerun")
        XCTAssertNil(PermissionResume.reopensOnboarding(
            PermissionResume(kind: .screenRecording, place: .traces, at: now), gateShows: false), "not onboarding's")
        XCTAssertNil(PermissionResume.reopensOnboarding(nil, gateShows: false))

        rerun.save(defaults)
        XCTAssertEqual(PermissionResume.peek(now: now.addingTimeInterval(5), defaults: defaults), rerun)
        XCTAssertNotNil(defaults.string(forKey: PermissionResume.defaultsKey), "peeking leaves it for onboarding")
        XCTAssertNil(PermissionResume.take(matching: { !$0.isOnboarding }, now: now, defaults: defaults),
                     "the shell's own resume never eats a rerun's marker")
        XCTAssertEqual(PermissionResume.take(matching: \.isOnboarding, now: now, defaults: defaults), rerun)
        XCTAssertNil(PermissionResume.peek(now: now.addingTimeInterval(PermissionResume.maxAge + 1), defaults: defaults))
    }

    /// The wiring that makes it so: a rerun's tick records the rerun place, the shell reopens onboarding in the mode the
    /// marker names, and onboarding lands on Sources and ticks the browser whatever its mode.
    func testTheRerunPlaceAndTheReopenAreWired() throws {
        func source(_ suffix: String) throws -> String {
            let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) })
            return try String(contentsOf: file, encoding: .utf8)
        }
        let view = try source("Views/Onboarding/OnboardingView.swift")
        XCTAssertTrue(view.contains("mode == .rerun ? .onboardingRerun(browser: browser) : .onboarding(browser: browser)"))
        let resume = try XCTUnwrap(view.range(of: "private func resumePermissionTick() {"))
        let body = String(view[resume.upperBound...].prefix(700))
        XCTAssertTrue(body.contains("ownerSaved = true"), "a rerun's owner is already saved")
        XCTAssertTrue(body.contains("go(.sources, .keyboard)"))
        XCTAssertTrue(body.contains("marker.place.browser"), "either place's browser is ticked again")
        XCTAssertFalse(body.contains("guard ownerSaved"), "never skipped for a rerun")
        let content = try source("/ContentView.swift")
        XCTAssertTrue(content.contains("PermissionResume.reopensOnboarding(PermissionResume.peek(), gateShows: false)"))
    }

    func testOnlyScreenRecordingAndFullDiskAccessWaitForARelaunch() {
        XCTAssertTrue(TracePermission.screenRecording.needsRelaunch)
        XCTAssertTrue(TracePermission.fullDiskAccess.needsRelaunch)
        XCTAssertFalse(TracePermission.accessibility.needsRelaunch)
    }

    /// Full Disk Access (Messages, Safari) is the drag helper; Calendar, Contacts, Reminders, Chrome's Automation and
    /// Notes keep macOS's own prompt — the helper has no kind for them.
    func testOnlyListsWithNoSystemPromptUseTheDragHelper() {
        XCTAssertEqual(Set(TracePermission.allCases), [.accessibility, .screenRecording, .fullDiskAccess])
        XCTAssertEqual(SourceTileGroups.deniedSettingsURL(.app(AppSourceDrivers.calendar))?.absoluteString,
                       "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")
        XCTAssertEqual(SourceTileGroups.deniedSettingsURL(.app(AppSourceDrivers.contacts))?.absoluteString,
                       "x-apple.systempreferences:com.apple.preference.security?Privacy_Contacts")
        XCTAssertNil(SourceTileGroups.deniedSettingsURL(.browser("safari")))
    }

    func testABrowserMacOSHidesShowsTheDragHelperForItsChannel() async {
        var asked: [String] = []
        var opened: [URL] = []
        var deps = FoundTurnOnDeps(wiring: { nil }, runtime: .developer(codeRoot: URL(fileURLWithPath: "/R")),
                                   connect: { _, _, _ in .done }, syncBrowser: { _ in "" },
                                   readiness: { _ in .needsPermission }, open: { opened.append($0) },
                                   commitDrop: { _ in nil }, refresh: {})
        deps.askFullDiskAccess = { asked.append($0) }
        let result = await FoundTurnOn.run(.browser("safari"), deps: deps)
        XCTAssertEqual(result, .needsPermission)
        XCTAssertEqual(asked, ["safari"])
        XCTAssertTrue(opened.isEmpty, "the helper opens the list on the person's Open, not the tick")
    }

    /// The new files never name a prompting API outside their comments.
    func testNoPromptingAPIInTheNewPermissionCode() throws {
        for name in ["PermissionResume.swift", "PermissionDragHelper.swift", "OnboardingV3.swift"] {
            let file = try XCTUnwrap(try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == name }, name)
            let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }.joined(separator: "\n")
            for banned in ["CGRequestScreenCaptureAccess", "AXIsProcessTrustedWithOptions", "kAXTrustedCheckOptionPrompt",
                           "SCShareableContent", "AEDeterminePermissionToAutomateTarget", "requestAccess(", "requestFullAccess"] {
                XCTAssertFalse(code.contains(banned), "\(name): \(banned)")
            }
        }
    }
}

// MARK: - 2. The first agent call

@MainActor
final class OnboardingV3FirstCallTests: XCTestCase {
    /// Review blocker 1: Cicada's own wiring check (`claude mcp get` initializes as Claude Code) and an agent merely
    /// starting a session move `lastSeenAt`; only a tool call moves `lastCalledAt`, and only that is a first call.
    func testAConnectOrAWiringProbeIsNeverACallOnlyAToolCallIs() {
        let start = [AgentLiveRow(id: "claude-code", connected: true, lastSeenAt: "2026-10-24T09:00:00Z", via: "mcp")]
        let baseline = FirstAgentCall.baseline(start)
        XCTAssertEqual(baseline, [:], "seen, never called")
        XCTAssertNil(FirstAgentCall.detect(baseline: baseline, rows: [
            AgentLiveRow(id: "claude-code", connected: true, lastSeenAt: "2026-10-24T09:00:03Z", via: "mcp"),
        ]), "the wiring probe's initialize moved lastSeenAt: no call")
        XCTAssertNil(FirstAgentCall.detect(baseline: baseline,
                                           rows: [AgentLiveRow(id: "codex", connected: true, via: "config")]),
                     "wired but never called is no call")
        XCTAssertEqual(FirstAgentCall.detect(baseline: baseline, rows: [
            AgentLiveRow(id: "claude-code", connected: true, lastSeenAt: "2026-10-24T09:01:00Z", via: "mcp",
                         lastCalledAt: "2026-10-24T09:01:00Z"),
        ]), "claude-code", "a tools/call")
    }

    func testOnlyACallLaterThanTheBaselineCounts() {
        let baseline = ["claude-code": "2026-10-24T09:00:00Z"]
        func row(_ called: String) -> [AgentLiveRow] {
            [AgentLiveRow(id: "claude-code", connected: true, lastSeenAt: called, via: "mcp", lastCalledAt: called)]
        }
        XCTAssertNil(FirstAgentCall.detect(baseline: baseline, rows: row("2026-10-24T09:00:00Z")), "the same call")
        XCTAssertNil(FirstAgentCall.detect(baseline: baseline, rows: row("2026-10-24T08:59:00Z")), "never backwards")
        XCTAssertEqual(FirstAgentCall.detect(baseline: baseline, rows: row("2026-10-24T09:00:01Z")), "claude-code")
        XCTAssertEqual(FirstAgentCall.detect(baseline: baseline, rows: row("2026-10-24T09:00:01.250Z")), "claude-code",
                       "fractional seconds read too")
    }

    func testTheProbeTakesItsBaselineFromTheFirstAnswerAndKeepsTheFirstCaller() {
        let probe = AgentLiveProbe(fetch: { AgentLiveResponse() })
        let early = "2026-10-24T08:00:00Z"
        probe.apply(AgentLiveResponse(agents: [AgentLiveRow(id: "claude-code", connected: true, lastSeenAt: early,
                                                            via: "mcp", lastCalledAt: early)]))
        XCTAssertNil(probe.firstCall, "the first answer is the baseline, never a call")
        probe.apply(AgentLiveResponse(agents: [AgentLiveRow(id: "claude-code", connected: true,
                                                            lastSeenAt: "2026-10-24T08:00:30Z", via: "mcp",
                                                            lastCalledAt: early)]))
        XCTAssertNil(probe.firstCall, "a reconnect (the wiring re-read after Connect) is not a call")
        probe.apply(AgentLiveResponse(agents: [AgentLiveRow(id: "claude-code", connected: true,
                                                            lastSeenAt: "2026-10-24T08:01:00Z", via: "mcp",
                                                            lastCalledAt: "2026-10-24T08:01:00Z")]))
        XCTAssertEqual(probe.firstCall, "claude-code")
        probe.apply(AgentLiveResponse(agents: [
            AgentLiveRow(id: "codex", connected: true, lastSeenAt: "2026-10-24T08:02:00Z", via: "mcp",
                         lastCalledAt: "2026-10-24T08:02:00Z"),
        ]))
        XCTAssertEqual(probe.firstCall, "claude-code", "the moment happens once")
    }

    func testAnOlderBackendWithoutLastCalledAtNeverConfirms() throws {
        let json = #"{"agents":[{"id":"claude-code","connected":true,"lastSeenAt":"2026-10-24T09:00:00Z","via":"mcp"}]}"#
        let response = try JSONDecoder().decode(AgentLiveResponse.self, from: Data(json.utf8))
        XCTAssertNil(response.agents.first?.lastCalledAt)
        XCTAssertNil(FirstAgentCall.detect(baseline: [:], rows: response.agents))
        let fresh = #"{"agents":[{"id":"codex","connected":true,"lastSeenAt":null,"via":null,"lastCalledAt":"2026-10-24T09:00:00Z"}]}"#
        XCTAssertEqual(try JSONDecoder().decode(AgentLiveResponse.self, from: Data(fresh.utf8)).agents.first?.lastCalledAt,
                       "2026-10-24T09:00:00Z")
    }

    func testTheChipNamesThePersonsOwnAgentOrNone() throws {
        let code = try XCTUnwrap(AgentCatalog.entry(for: "claude-code"))
        let codex = try XCTUnwrap(AgentCatalog.entry(for: "codex"))
        let found = AgentStepRow(entry: code, connected: false, action: .preparing, name: "Claude Code")
        let calling = AgentStepRow(entry: codex, connected: true, action: .none, name: "Codex")
        let rows = [AgentUmbrellaRow(id: "anthropic", label: "Anthropic", logo: "claude", products: [found]),
                    AgentUmbrellaRow(id: "openai", label: "OpenAI", logo: "openai", products: [calling])]
        XCTAssertEqual(AgentTryPrompt.agentName(rows), "Codex", "the one already calling first")
        XCTAssertEqual(AgentTryPrompt.agentName([rows[0]]), "Claude Code", "else the first found here")
        XCTAssertNil(AgentTryPrompt.agentName([]))
        XCTAssertEqual(Copy.agentsTryAsk(nil), "Ask your agent: what do you remember about me?")
        XCTAssertEqual(Copy.agentsTryAsk("Codex"), "Ask Codex: what do you remember about me?")
        XCTAssertEqual(Copy.agentsTryPrompt, "What do you remember about me?", "the copy button copies the question")
        XCTAssertEqual(AgentTryPrompt.callerName("codex", rows: rows), "Codex")
        XCTAssertEqual(Copy.agentsFirstCall("Codex"), "Codex just called me. It works.")
    }

    /// Provider-neutral copy: the step never names a vendor of its own accord.
    func testTheStepNamesNoVendorOfItsOwn() {
        for line in [Copy.agentsTryAsk(nil), Copy.agentsTryLead, Copy.agentsOther, Copy.agentsOtherSummary] {
            for vendor in ["Claude", "ChatGPT", "Codex", "OpenAI", "Gemini", "Cursor"] {
                XCTAssertFalse(line.contains(vendor), "\(line) names \(vendor)")
            }
        }
    }
}

// MARK: - 3. Done ends on the person's own memory

final class OnboardingV3DoneTests: XCTestCase {
    func testNothingYetSaysSoWithNoLabel() {
        let reveal = DoneReveal.of(pages: [], waiting: [], reading: false)
        XCTAssertTrue(reveal.isEmpty)
        XCTAssertEqual(reveal.more, 0)
        XCTAssertNil(reveal.label, "an empty list says \"Nothing yet.\" on its own")
        XCTAssertEqual(Copy.doneEmpty, "Nothing yet.")
    }

    func testPagesComeFirstThenConversationsAndTheRestIsCounted() {
        let reveal = DoneReveal.of(
            pages: [DoneReveal.Page(id: "alpha-project", name: "Alpha Project")],
            waiting: [DoneReveal.Conversation(id: "ep_1", title: "Planning the trip", origin: "claude-export"),
                      DoneReveal.Conversation(id: "ep_2", title: "  ", origin: "chatgpt-export"),
                      DoneReveal.Conversation(id: "ep_3", title: nil, origin: "claude-code"),
                      DoneReveal.Conversation(id: "ep_4", title: "Later", origin: "claude-code")],
            reading: false)
        XCTAssertEqual(reveal.items.map(\.title), ["Alpha Project", "Planning the trip", Copy.doneUntitled])
        XCTAssertEqual(reveal.items.first?.kind, .page)
        XCTAssertEqual(reveal.items[1].kind, .conversation(origin: "claude-export"))
        XCTAssertEqual(reveal.more, 2)
        XCTAssertEqual(reveal.label, Copy.doneAlready)
        XCTAssertEqual(Copy.doneMore(2), "and 2 more")
    }

    func testAReadThatIsRunningSaysReadingNow() {
        XCTAssertEqual(DoneReveal.of(pages: [], waiting: [], reading: true).label, Copy.doneReading)
        XCTAssertEqual(DoneReveal.of(pages: [DoneReveal.Page(id: "a", name: "A")], waiting: [], reading: true).label,
                       Copy.doneReading)
    }

    func testTheOwnersSeededPageFacetsAndHubsAreNotSomethingThatCameIn() {
        let nodes = [GraphNode(id: "verify-person", name: "Verify Person", type: .person, isOwner: true),
                     GraphNode(id: "bob-example#work", name: "Work", type: .person, isFacet: true, parentId: "bob-example"),
                     GraphNode(id: "hub-1", name: "Hub", type: .hub, isHub: true),
                     GraphNode(id: "alpha-project", name: "Alpha Project", type: .project)]
        XCTAssertEqual(DoneReveal.pages(nodes), [DoneReveal.Page(id: "alpha-project", name: "Alpha Project")])
    }

    /// Owner ruling (new installs read nightly at 03:00, plus once after an import): Done itself never starts a read.
    /// Its only run is Open Cicada's existing one-time read after something came in (`DoneLine.readsNow`); the reveal
    /// only reads the graph, the status and the queue.
    func testDoneStartsNoReadOfItsOwn() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Onboarding/DonePage.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("triggerManually"))
        let view = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Onboarding/OnboardingView.swift")
        })
        let source = try String(contentsOf: view, encoding: .utf8)
        XCTAssertEqual(source.components(separatedBy: "triggerManually").count - 1, 1,
                       "one read, the existing post-import one on Open Cicada")
        let refresh = try XCTUnwrap(source.range(of: "private func refreshReveal() async {"))
        let body = source[refresh.upperBound...].prefix(200)
        XCTAssertFalse(body.contains("trigger"), "the reveal reads, it never starts")
    }
}

// MARK: - 4. The real menu-bar worm

@MainActor
final class OnboardingV3WormTests: XCTestCase {
    func testTheHelloIsThePosesOwnFramesOnTheirSheetTimes() {
        let beats = MenuBarGreeting.beats(frameCount: 5, seconds: [1.6, 0.16, 0.16, 0.4, 1.2])
        XCTAssertEqual(beats.map(\.step), [1, 2, 3, 4], "after the key frame, to the end")
        XCTAssertEqual(beats.map(\.hold), [0.16, 0.16, 0.4, 1.2], "ruling 18: the sheet's own timings")
        XCTAssertTrue(MenuBarGreeting.beats(frameCount: 1, seconds: [1]).isEmpty)
        XCTAssertTrue(MenuBarGreeting.beats(frameCount: 4, seconds: []).isEmpty)
        let art = BookwormArt.clip(MenuBarGreeting.pose, look: .idle, set: .small)
        XCTAssertGreaterThan(art?.1.order.count ?? 0, 1, "the happy sheet has frames to play")
    }

    func testTheHelloOnlyPlaysWhereItCanBeSeenAndNeverUnderReduceMotion() {
        XCTAssertTrue(MenuBarGreeting.greets(isVisible: true, reduceMotion: false, flying: false))
        XCTAssertFalse(MenuBarGreeting.greets(isVisible: false, reduceMotion: false, flying: false), "a waiting worm")
        XCTAssertFalse(MenuBarGreeting.greets(isVisible: true, reduceMotion: true, flying: false), "DR-66")
        XCTAssertFalse(MenuBarGreeting.greets(isVisible: true, reduceMotion: false, flying: true), "mid-flight")
    }

    func testAWaitingWormKeepsItsNumberWhileItSaysHello() {
        let plain = BookwormRenderer.cacheKey(state: .curious(count: 3), rectIndex: 12, pointSize: 18)
        let posed = BookwormRenderer.smallImage(state: .curious(count: 3), frameStep: 1, pointSize: 18,
                                                pose: MenuBarGreeting.pose)
        XCTAssertEqual(posed.size, NSSize(width: 18, height: 18))
        XCTAssertFalse(plain.contains("pose"), "an ordinary frame's key is unchanged")
    }

    /// On a rerun the real item is already up there: the step points at it and asks it to say hello.
    func testTheStepAsksTheRealWormToReact() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Onboarding/OnboardingView.swift")
        })
        let view = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(view.contains("if next == .menuBar { menuBar?.greet() }"))
        let manager = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("MenuBarManager.swift") })
        XCTAssertTrue(try String(contentsOf: manager, encoding: .utf8).contains("self?.greet()"),
                      "a first run's worm says it on landing")
    }
}

// MARK: - 5. Every way out shows the worm

@MainActor
final class OnboardingV3ExitTests: XCTestCase {
    private var defaults: UserDefaults!
    private let suite = "OnboardingV3ExitTests"

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    func testEveryExitLetsAWaitingWormIntoTheMenuBar() {
        let frame = CGRect(x: 100, y: 100, width: 108, height: 108)
        for exit in OnboardingExit.allCases {
            for reduceMotion in [false, true] {
                defaults.removePersistentDomain(forName: suite)
                let manager = MenuBarManager()
                manager.setIntroPhase(.waiting)
                XCTAssertFalse(manager.isVisible)
                manager.introduce(exit.reveal(from: frame, reduceMotion: reduceMotion), defaults: defaults)
                XCTAssertTrue(manager.isVisible, "\(exit), reduce motion \(reduceMotion)")
                XCTAssertEqual(MenuBarIntro.phase(defaults), .done)
            }
        }
    }

    func testOnlyAPointersOpenCicadaFlies() {
        let frame = CGRect(x: 1, y: 1, width: 9, height: 9)
        XCTAssertEqual(OnboardingExit.openCicadaByPointer.reveal(from: frame, reduceMotion: false), .fly(from: frame))
        XCTAssertEqual(OnboardingExit.openCicadaByPointer.reveal(from: frame, reduceMotion: true), .fade, "DR-66")
        for exit in OnboardingExit.allCases where exit != .openCicadaByPointer {
            XCTAssertEqual(exit.reveal(from: frame, reduceMotion: false), .instant, "\(exit): no flight (DR-60)")
        }
    }

    /// The window closing on any path still introduces the worm, and Skip on the worm's step never strands it.
    func testTheCatchAllAndSkipStillStand() throws {
        let content = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("/ContentView.swift") })
        XCTAssertTrue(try String(contentsOf: content, encoding: .utf8).contains("if !showing { menuBar?.introduce(.instant) }"))
        XCTAssertTrue(OnboardingPage.menuBar.skippable)
        XCTAssertEqual(OnboardingPage.menuBar.next, .done)
    }

    /// Hyrum: no step id or stored name moved, so a saved step resumes where it did. *Saved lists* (2026-10-26) adds a
    /// new name; every earlier one is unchanged.
    func testSavedProgressStillResumes() {
        XCTAssertEqual(OnboardingPage.allCases.map(\.storedName),
                       ["welcome", "intelligence", "agents", "sources", "savedLists", "menuBar", "done"])
        for (stored, page) in [("agents", OnboardingPage.agents), ("menuBar", .menuBar), ("done", .done),
                               ("import", .sources), ("whoReads", .intelligence), ("ready", .done)] {
            XCTAssertEqual(OnboardingPage(stored: stored), page, stored)
        }
    }
}

// MARK: - 6. Fewer words, one action per step

final class OnboardingV3WordsTests: XCTestCase {
    func testTitlesAreSevenWordsOrFewerAndBodiesTwentyFive() {
        for step in OnboardingWords.steps {
            let title = OnboardingWords.count([step.title])
            let body = OnboardingWords.count(step.body)
            XCTAssertLessThanOrEqual(title, OnboardingWords.titleCap, "\(step.name) title: \(title) words")
            XCTAssertLessThanOrEqual(body, OnboardingWords.bodyCap, "\(step.name) body: \(body) words")
        }
        XCTAssertEqual(OnboardingWords.count(["I read tonight at 3:00 AM — ok · fine."]), 7, "a word has a letter")
    }

    func testTheWormSpeaksCalmlyWithAtMostOneJoke() {
        let lines = OnboardingWords.steps.flatMap { [$0.title] + $0.body }
        for line in lines {
            XCTAssertFalse(line.contains("!"), "DR-59: \(line)")
            let letters = line.filter(\.isLetter)
            XCTAssertNotEqual(letters, letters.uppercased(), "no ALL CAPS: \(line)")
        }
        XCTAssertTrue(Copy.sourcesSubline.hasPrefix("Tick what I may read"), "first person")
        XCTAssertTrue(Copy.MeetWorm.number.hasPrefix("My number"))
        XCTAssertEqual(Copy.doneTitle, "That's it. I'll take it from here.", "the flow's one wink")
    }

    /// DR-39: the secondary rows start folded — the accounts and Messages on Sources, the other agents on Agents.
    func testSecondaryRowsFold() {
        let tiles = SourceTiles.tiles(imports: ImportCatalog.entries(ImportContext()))
        let groups = SourceTileGroups.split(tiles)
        XCTAssertEqual(groups.lead.map(\.title), ["Calendar", Copy.contactsTitle, Copy.sourcesChats])
        XCTAssertEqual(groups.more.map(\.title), ["Messages", "YouTube", "X", "Instagram"])
        XCTAssertFalse(SourceTileGroups.moreStartsOpen(remembered: false, anyOnInside: false))
        XCTAssertTrue(SourceTileGroups.moreStartsOpen(remembered: false, anyOnInside: true), "what is on is never hidden")
        XCTAssertTrue(SourceTileGroups.moreStartsOpen(remembered: true, anyOnInside: false))
    }
}
