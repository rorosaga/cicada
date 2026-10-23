import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G191 v7 — the notch, second version (owner 2026-10-23):
///
/// 2. "For the first couple of newlines, have the text input vertically expand smoothly until a limit arrives where it
///    becomes scrollable." — `SaveWhyField`: one line, growing to five, then scrolling.
/// 3. "I'd like more options that appear smoothly based on the content being saved … from our bank: found it funny,
///    good asset for video, moodboard potential, interesting design, product, inspiration, aesthetic … let's have a lot
///    of options." — the four stay the fixed first row; a few from a bank of 38 fade in under them, ranked on the Mac by
///    the site, the link's words, the person's past picks and (only when installed) the search model.
///
/// Synthetic links only; nothing reads a browser and nothing reaches the network.
@MainActor
final class SaveWhySuggestTests: XCTestCase {
    private let channel = "chrome-bookmarks"

    // MARK: - The fixture both sides read

    private struct ReasonsFixture: Decodable {
        let reasons: [SavedWhyOptions.Reason]
        let more: [SavedWhyOptions.Reason]
    }

    private func fixture() throws -> ReasonsFixture {
        // …/Tests/CicadaAppTests/<this file> → repo root
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let file = root.appendingPathComponent("api/tests/fixtures/saved_why_reasons.json")
        let decoded = try JSONDecoder().decode(ReasonsFixture.self, from: Data(contentsOf: file))
        XCTAssertGreaterThanOrEqual(decoded.more.count, 30, "read \(decoded.more.count) bank reasons from \(file.path)")
        return decoded
    }

    private var bank: [SavedWhyOptions.Reason] { (try? fixture().more) ?? [] }

    // MARK: - (2) The field grows to a cap, then scrolls

    func testTheFieldGrowsALineAtATimeUpToFiveThenScrolls() {
        let width: CGFloat = 360
        XCTAssertEqual(SaveWhyField.lineCount("", width: width), 1, "empty is one line, never zero")
        XCTAssertEqual(SaveWhyField.lineCount("a few words", width: width), 1)
        XCTAssertEqual(SaveWhyField.lineCount("one\ntwo\nthree", width: width), 3, "each line break is a line")
        XCTAssertEqual(SaveWhyField.lineCount("one\n", width: width), 2, "a trailing break opens the next line")
        let long = String(repeating: "the colours on the hero section ", count: 8)
        XCTAssertGreaterThan(SaveWhyField.lineCount(long, width: width), 2, "long words wrap and grow the field too")
        XCTAssertEqual(SaveWhyField.lineCount(long, width: width), SaveWhyField.lineCount(long, width: width))

        let six = (1...6).map { "line \($0)" }.joined(separator: "\n")
        XCTAssertEqual(SaveWhyField.lineCount(six, width: width), 6)
        XCTAssertEqual(SaveWhyField.maxLines, 5)
        XCTAssertEqual(SaveWhyField.visibleLines(1), 1)
        XCTAssertEqual(SaveWhyField.visibleLines(3), 3)
        XCTAssertEqual(SaveWhyField.visibleLines(6), 5, "past the cap the field scrolls; it never grows further")
        XCTAssertEqual(SaveWhyField.visibleLines(0), 1)
        let line = SaveWhyField.lineHeight()
        XCTAssertGreaterThan(line, 10)
        XCTAssertEqual(SaveWhyField.textHeight(lines: 1, lineHeight: line), line)
        XCTAssertEqual(SaveWhyField.textHeight(lines: 9, lineHeight: line), 5 * line)
        // The window is made tall enough up front for the field at its cap and two rows of suggestions.
        XCTAssertGreaterThanOrEqual(SaveWhyField.growthReserve, 4 * line)
    }

    /// The growth eases through `CicadaMotion` (DR-61) and is gone under Reduce Motion (DR-66); the suggestions keep
    /// only their fade there.
    func testTheGrowthEasesAndStopsUnderReduceMotion() {
        XCTAssertNotNil(CicadaMotion.fieldGrow(reduceMotion: false))
        XCTAssertNil(CicadaMotion.fieldGrow(reduceMotion: true))
        XCTAssertNotNil(CicadaMotion.suggestGrow(reduceMotion: false))
        XCTAssertNil(CicadaMotion.suggestGrow(reduceMotion: true))
        XCTAssertLessThanOrEqual(CicadaMotion.fieldGrowDuration, 0.15, "never trails the typing")
        XCTAssertLessThan(SaveWhyPolicy.suggestBudget, SaveWhyPolicy.armDelay)
    }

    // MARK: - The fixed first row never moves

    func testTheFourStayTheFixedFirstRowInTheirOrder() throws {
        let fixture = try fixture()
        XCTAssertEqual(SavedWhyOptions.basic.reasons, fixture.reasons)
        XCTAssertEqual(SavedWhyOptions.basic.reasons.map(\.key), ["design", "product", "read_later", "someday"])
        XCTAssertTrue(SavedWhyOptions.basic.more.isEmpty, "no bank until the backend says which keys it knows")
        XCTAssertTrue(Set(fixture.more.map(\.key)).isDisjoint(with: fixture.reasons.map(\.key)))

        // The backend's options: `reasons` is still the four; the bank rides in `more`; an older backend has none.
        let json = """
        {"reasons": \(String(data: try JSONEncoder().encode(fixture.reasons), encoding: .utf8)!),
         "more": \(String(data: try JSONEncoder().encode(fixture.more), encoding: .utf8)!),
         "projects": [], "maxText": 500}
        """
        let options = try JSONDecoder().decode(SavedWhyOptions.self, from: Data(json.utf8))
        XCTAssertEqual(options.reasons, fixture.reasons)
        XCTAssertEqual(options.more, fixture.more)
        XCTAssertEqual(options.order, fixture.reasons.map(\.key) + fixture.more.map(\.key))
        let older = try JSONDecoder().decode(SavedWhyOptions.self, from: Data("""
            {"reasons": [{"key": "design", "label": "The design"}], "projects": [], "maxText": 500}
            """.utf8))
        XCTAssertTrue(older.more.isEmpty)
        XCTAssertEqual(older.order, ["design"])

        for url in ["https://www.youtube.com/watch?v=x", "https://www.pinterest.com/pin/1/", "https://github.com/a/b",
                    "https://alpha.example/"] {
            let shown = SaveWhySuggest.rank(url: url, title: "", bank: options.more, picks: []).map(\.key)
            XCTAssertTrue(Set(shown).isDisjoint(with: fixture.reasons.map(\.key)), "the fixed four are never suggested")
        }
    }

    // MARK: - (3) Ranking: the site, the words, past picks, the model only when installed

    func testTheSiteLeadsTheSuggestions() {
        let youtube = SaveWhySuggest.rank(url: "https://www.youtube.com/watch?v=abc", title: "A launch film",
                                          bank: bank, picks: []).map(\.key)
        XCTAssertEqual(Array(youtube.prefix(2)), ["to_watch", "video_asset"])
        let pinterest = SaveWhySuggest.rank(url: "https://www.pinterest.com/pin/123/", title: "Living room",
                                            bank: bank, picks: []).map(\.key)
        XCTAssertEqual(pinterest.first, "moodboard")
        XCTAssertTrue(pinterest.contains("aesthetic") && pinterest.contains("inspiration"))
        let github = SaveWhySuggest.rank(url: "https://github.com/alpha/beta", title: "alpha/beta: a sync engine",
                                         bank: bank, picks: []).map(\.key)
        XCTAssertEqual(Array(github.prefix(2)), ["tool_to_try", "code"])
        // A subdomain counts as its platform; a host that merely contains a name does not.
        XCTAssertEqual(SaveWhySuggest.rank(url: "https://music.youtube.com/watch?v=1", title: "", bank: bank, picks: [])
            .first?.key, "to_watch")
        XCTAssertNotEqual(SaveWhySuggest.rank(url: "https://notyoutube.example/", title: "", bank: bank, picks: [])
            .first?.key, "to_watch")
        for list in [youtube, pinterest, github] {
            XCTAssertTrue((SaveWhySuggest.minShown...SaveWhySuggest.maxShown).contains(list.count), "\(list)")
            XCTAssertEqual(Set(list).count, list.count)
        }
    }

    func testTheLinksOwnWordsCountButNeverItsQuery() {
        let recipe = SaveWhySuggest.rank(url: "https://alpha.example/blog/best-pancake-recipe", title: "Pancakes",
                                         bank: bank, picks: []).map(\.key)
        XCTAssertEqual(recipe.first, "recipe")
        let query = SaveWhySuggest.rank(url: "https://alpha.example/page?q=recipe&token=font", title: "",
                                        bank: bank, picks: []).map(\.key)
        XCTAssertEqual(query, SaveWhySuggest.fallback, "the query string is never read")
    }

    func testThePersonsOwnPastPicksLiftAReasonOnThatSiteAndOverall() {
        let url = "https://github.com/alpha/gamma"
        let before = SaveWhySuggest.rank(url: url, title: "", bank: bank, picks: []).map(\.key)
        XCTAssertFalse(before.contains("inspiration"))
        // This person saves repositories for inspiration, three times on GitHub.
        let picks = (0..<3).map { _ in SaveWhySuggest.Pick(site: "github.com", reasons: ["inspiration", "design"]) }
        let after = SaveWhySuggest.rank(url: url, title: "", bank: bank, picks: picks).map(\.key)
        XCTAssertTrue(after.contains("inspiration"))
        XCTAssertLessThan(after.firstIndex(of: "inspiration")!, after.firstIndex(of: "reference") ?? .max)
        // On another site the same picks count only as overall habit — a third of what they count on GitHub.
        let keys = bank.map(\.key)
        let onGitHub = SaveWhySuggest.scores(url: url, title: "", keys: keys, picks: picks, model: nil)["inspiration"]
        let onPinterest = SaveWhySuggest.scores(url: "https://www.pinterest.com/pin/9/", title: "", keys: keys,
                                                picks: picks, model: nil)["inspiration"]
        let pinterestLean = SaveWhySuggest.scores(url: "https://www.pinterest.com/pin/9/", title: "", keys: keys,
                                                  picks: [], model: nil)["inspiration"]
        XCTAssertEqual((onGitHub ?? 0), 5.7, accuracy: 0.001)
        XCTAssertEqual((onPinterest ?? 0) - (pinterestLean ?? 0), 1.2, accuracy: 0.001)
        // Overall habit alone still reaches an unknown site.
        let habit = (0..<5).map { _ in SaveWhySuggest.Pick(site: "beta.example", reasons: ["funny"]) }
        XCTAssertEqual(SaveWhySuggest.rank(url: "https://alpha.example/", title: "", bank: bank, picks: habit).first?.key,
                       "funny")
        // A fixed-row pick or an unknown key is never suggested.
        XCTAssertFalse(SaveWhySuggest.rank(url: url, title: "", bank: bank, picks: picks).map(\.key).contains("design"))
    }

    func testWithNoSignalAndNoModelTheGenericThreeStand() {
        let none = SaveWhySuggest.rank(url: "https://alpha.example/x", title: "", bank: bank, picks: [], model: nil)
        XCTAssertEqual(none.map(\.key), SaveWhySuggest.fallback)
        XCTAssertEqual(none.map(\.label), ["Inspiration", "A reference", "An idea to explore"])
        XCTAssertTrue(SaveWhySuggest.rank(url: "https://alpha.example/", title: "", bank: [], picks: []).isEmpty,
                      "no bank from the backend, no suggestions")
    }

    func testTheModelOnlyAddsWhenItAnswered() {
        let url = "https://alpha.example/x"
        var scores = Dictionary(uniqueKeysWithValues: bank.map { ($0.key, 0.1) })
        scores["travel"] = 0.9
        scores["place"] = 0.7
        let ranked = SaveWhySuggest.rank(url: url, title: "", bank: bank, picks: [], model: scores).map(\.key)
        XCTAssertEqual(Array(ranked.prefix(2)), ["travel", "place"])
        // The site still outranks a model's lean on a known platform.
        let youtube = SaveWhySuggest.rank(url: "https://youtube.com/watch?v=1", title: "", bank: bank, picks: [],
                                          model: scores).map(\.key)
        XCTAssertEqual(youtube.first, "to_watch")
        // Flat scores carry no information and change nothing.
        let flat = Dictionary(uniqueKeysWithValues: bank.map { ($0.key, 0.5) })
        XCTAssertEqual(SaveWhySuggest.rank(url: url, title: "", bank: bank, picks: [], model: flat).map(\.key),
                       SaveWhySuggest.fallback)
    }

    func testAChosenReasonIsAlwaysShownFirst() {
        let ranked = SaveWhySuggest.rank(url: "https://youtube.com/watch?v=1", title: "", bank: bank, picks: [],
                                         pinned: ["recipe"]).map(\.key)
        XCTAssertEqual(ranked.first, "recipe")
    }

    func testPastPicksComeFromTheAnswersTheBankHolds() throws {
        let json = """
        [{"mediaEntityId": "m1", "url": "https://m.youtube.com/watch?v=1", "title": "One", "mediaType": "video",
          "savedWhyHistory": [{"reasons": ["to_watch"], "labels": ["To watch later"]},
                              {"reasons": ["funny", "design"], "labels": ["Found it funny", "The design"]}]},
         {"mediaEntityId": "m2", "url": "https://alpha.example/a", "title": "Two", "mediaType": "article",
          "savedWhy": {"reasons": [], "labels": [], "text": "only words"}},
         {"mediaEntityId": "m3", "url": "https://beta.example/b", "title": "Three", "mediaType": "article"}]
        """
        let items = try JSONDecoder().decode([MediaFeedItem].self, from: Data(json.utf8))
        XCTAssertEqual(SaveWhySuggest.picks(from: items), [
            .init(site: "youtube.com", reasons: ["to_watch"]), .init(site: "youtube.com", reasons: ["funny", "design"]),
        ])
        XCTAssertEqual(SaveWhySuggest.site(of: "https://news.bbc.co.uk/x"), "bbc.co.uk")
        XCTAssertEqual(SaveWhySuggest.site(of: "https://www.github.com/a"), "github.com")
    }

    // MARK: - The panel: suggestions arrive, a tap is stored exactly as a reason always was

    private func center(_ api: SuggestFakeAPI, presenter: (any SaveWhyPresenting)? = nil) async -> SaveWhyCenter {
        let defaults = UserDefaults(suiteName: "SaveWhySuggestTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let tick = SuggestTick()
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, uptime: { tick.next() })
        await center.refreshOptions()
        return center
    }

    private func look(_ url: String, title: String) -> BookmarkSyncResult {
        var r = BookmarkSyncResult(new: 0, skipped: 1, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: channel, found: 2, new: 0, skipped: 1,
                                      firstSync: false)])
        r.fresh = [FreshBookmark(url: url, title: title, origin: "chrome-bookmark", channel: channel,
                                 addedAt: ISO8601DateFormatter().string(from: Date()))]
        r.freshTotal = 1
        return r
    }

    private func waitForSuggestions(_ center: SaveWhyCenter) async throws {
        for _ in 0..<100 where center.suggestions.isEmpty { try await Task.sleep(for: .milliseconds(10)) }
    }

    func testASuggestedReasonIsStoredExactlyAsAReasonAlwaysWas() async throws {
        let api = SuggestFakeAPI(more: bank)
        let center = await center(api)
        await center.noticed(look("https://www.pinterest.com/pin/42/", title: "Reading nook"), live: true)
        XCTAssertEqual(center.options.reasons.map(\.key), ["design", "product", "read_later", "someday"])
        try await waitForSuggestions(center)
        XCTAssertEqual(center.suggestions.first?.key, "moodboard")
        center.input(.tapReason("moodboard"))
        center.input(.tapReason("design"))
        center.send(.draftChanged("the light\non the shelves"))
        center.input(.submit)
        await center.settle()
        let posts = await api.posts
        XCTAssertEqual(posts.count, 1)
        // The fixed row first, then the bank, as `LABELS` orders them; the words as typed (the backend folds them).
        XCTAssertEqual(posts.first?.answer, SavedWhyAnswer(reasons: ["design", "moodboard"],
                                                           text: "the light on the shelves"))
        XCTAssertEqual(posts.first?.answer.body["reasons"] as? [String], ["design", "moodboard"])
        XCTAssertEqual(Set((posts.first?.answer.body ?? [:]).keys), ["reasons", "text"], "the wire's shape is unchanged")
    }

    /// No search model installed: the backend answers `basis: none` and the panel ranks on its own — and nothing in
    /// the panel's code can start the model's download (only the Settings click does, `POST /embeddings/install`).
    func testWithNoModelInstalledThePanelRanksAloneAndNeverDownloads() async throws {
        let api = SuggestFakeAPI(more: bank)
        let center = await center(api)
        await center.noticed(look("https://github.com/alpha/beta", title: "alpha/beta"), live: true)
        try await waitForSuggestions(center)
        XCTAssertEqual(Array(center.suggestions.map(\.key).prefix(2)), ["tool_to_try", "code"])
        let asked = await api.suggestAsked
        XCTAssertEqual(asked, ["https://github.com/alpha/beta"], "asked once, for this link")
        let direct = await SaveWhyCenter.modelScores(api: api, url: "https://github.com/alpha/beta", title: "")
        XCTAssertNil(direct, "basis none: no scores, no download")

        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/SaveWhy")
        let files = try FileManager.default.contentsOfDirectory(at: sources, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "swift" }
        XCTAssertGreaterThan(files.count, 5, "found the panel's sources under \(sources.path)")
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["embeddings/install", "installEmbedding", "embeddings/choice", "chooseEmbedding"] {
                XCTAssertFalse(text.contains(needle), "\(file.lastPathComponent) names \(needle)")
            }
        }
    }

    /// The installed model's scores join the ranking when they arrive within the budget; a slow answer never waits the
    /// panel out and never reorders chips on screen.
    func testTheModelsScoresJoinOnlyWithinTheBudget() async throws {
        var scores = Dictionary(uniqueKeysWithValues: bank.map { ($0.key, 0.1) })
        scores["travel"] = 0.95
        let quick = SuggestFakeAPI(more: bank, scores: scores)
        let center = await center(quick)
        await center.noticed(look("https://alpha.example/x", title: ""), live: true)
        try await waitForSuggestions(center)
        XCTAssertEqual(center.suggestions.first?.key, "travel")

        let slow = SuggestFakeAPI(more: bank, scores: scores, delay: SaveWhyPolicy.suggestBudget + 0.5)
        let late = await self.center(slow)
        let started = Date()
        await late.noticed(look("https://alpha.example/y", title: ""), live: true)
        try await waitForSuggestions(late)
        XCTAssertLessThan(Date().timeIntervalSince(started), SaveWhyPolicy.suggestBudget + 0.4)
        XCTAssertEqual(late.suggestions.map(\.key), SaveWhySuggest.fallback, "past the budget the panel ranks alone")
        try await Task.sleep(for: .seconds(0.6))
        XCTAssertEqual(late.suggestions.map(\.key), SaveWhySuggest.fallback, "a late answer reorders nothing")
    }

    /// A tap on a chip that has only just appeared was aimed at what was there before (the same rule as the panel's).
    func testATapAsTheSuggestionsAppearIsIgnored() async throws {
        let api = SuggestFakeAPI(more: bank)
        let defaults = UserDefaults(suiteName: "SaveWhySuggestTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let clock = SuggestClock()
        let center = SaveWhyCenter(prefs: prefs, api: api, uptime: { clock.now })
        await center.refreshOptions()
        await center.noticed(look("https://www.pinterest.com/pin/1/", title: ""), live: true)
        clock.now += 1   // past the panel's own arm delay
        try await waitForSuggestions(center)
        center.input(.tapReason("moodboard"))
        XCTAssertEqual(center.lastIgnored, .tapReason("moodboard"))
        XCTAssertFalse(center.state?.isSelected(reason: "moodboard") ?? true)
        clock.now += SaveWhyPolicy.armDelay
        center.input(.tapReason("moodboard"))
        XCTAssertTrue(center.state?.isSelected(reason: "moodboard") ?? false)
    }

    /// A pending panel (Chrome's bubble, no link yet) suggests nothing until the link is known, then once.
    func testAPendingPanelSuggestsOnceItsLinkIsNamed() async throws {
        let api = SuggestFakeAPI(more: bank)
        let center = await center(api)
        center.bubbleSeen(channel: channel)
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertTrue(center.suggestions.isEmpty)
        center.candidate(FreshBookmark(url: "https://www.youtube.com/watch?v=q", title: "A film", origin: "chrome-bookmark",
                                       channel: channel, addedAt: ISO8601DateFormatter().string(from: Date())))
        try await waitForSuggestions(center)
        XCTAssertEqual(center.suggestions.first?.key, "to_watch")
        let asked = await api.suggestAsked
        XCTAssertEqual(asked.count, 1)
    }

    /// A saved answer with a bank reason, opened on the star again: the reason shows selected among the suggestions,
    /// and leaving unchanged writes nothing.
    func testAnEditedAnswersBankReasonIsShownAndKept() async throws {
        let api = SuggestFakeAPI(more: bank)
        let center = await center(api)
        center.bubbleSeen(channel: channel)
        let item = FreshBookmark(url: "https://github.com/alpha/beta", title: "beta", origin: "chrome-bookmark",
                                 channel: channel)
        center.adopt(ExistingBookmark(item: item, answer: SavedWhyAnswer(reasons: ["product", "recipe"]),
                                      at: "2026-10-20T10:00:00+00:00"))
        try await waitForSuggestions(center)
        XCTAssertEqual(center.suggestions.first?.key, "recipe")
        XCTAssertTrue(center.state?.isSelected(reason: "recipe") ?? false)
        XCTAssertEqual(center.state?.selection.reasons, ["product", "recipe"])
        center.send(.escape)
        await center.settle()
        let edits = await api.edits
        XCTAssertTrue(edits.isEmpty, "unchanged: nothing written")
    }

    // MARK: - The window: as tall as the card can grow, the band below it never swallowing a click

    func testTheWindowLeavesRoomToGrowAndAClickBelowTheCardLeaves() async throws {
        let api = SuggestFakeAPI(more: bank)
        let controller = SaveWhyPanelController()
        let center = await center(api, presenter: controller)
        await center.noticed(look("https://www.youtube.com/watch?v=w", title: "A film"), live: true)
        let panel = try XCTUnwrap(controller.window)
        for _ in 0..<50 where panel.cardHeight == 0 { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertGreaterThan(panel.cardHeight, 100)
        XCTAssertLessThan(panel.frame.height, 900, "the window's size is the card's plus the reserve, never the screen")
        XCTAssertGreaterThanOrEqual(panel.frame.height - panel.cardHeight + 1, SaveWhyField.growthReserve - 1,
                                    "room below the card for the field at its cap and two rows of suggestions")
        XCTAssertTrue(SaveWhyNSPanel.isBelowCard(CGPoint(x: 10, y: 5), windowHeight: 400, cardHeight: 250))
        XCTAssertFalse(SaveWhyNSPanel.isBelowCard(CGPoint(x: 10, y: 200), windowHeight: 400, cardHeight: 250))
        XCTAssertFalse(SaveWhyNSPanel.isBelowCard(CGPoint(x: 10, y: 5), windowHeight: 400, cardHeight: 0),
                       "before layout nothing is treated as outside")

        center.input(.tapReason("design"))
        let below = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: CGPoint(x: 30, y: 4),
                                                     modifierFlags: [], timestamp: 0, windowNumber: panel.windowNumber,
                                                     context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
        panel.sendEvent(below)
        XCTAssertFalse(panel.clickedInside, "a click in the clear band never takes the keyboard")
        await center.settle()
        XCTAssertFalse(center.isShowing, "it leaves, as a click anywhere else does")
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["design"])], "keeping what was chosen")
    }

    // MARK: - Screenshots (a render harness: the real notch needs a Chrome bookmark)

    /// Renders the panel as it draws in the notch — 1, 3 and 6 lines; YouTube, Pinterest and GitHub suggestions — in
    /// both appearances, into `SAVE_NOTCH_SHOTS_DIR`. Skipped unless that is set.
    func testRenderTheNotchShots() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SAVE_NOTCH_SHOTS_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SAVE_NOTCH_SHOTS_DIR to render the save-notch screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        let cases: [(name: String, url: String, title: String, text: String)] = [
            ("lines-1", "https://www.youtube.com/watch?v=demo", "Alpha launch film", "The pacing of the intro"),
            ("lines-3", "https://www.youtube.com/watch?v=demo", "Alpha launch film",
             "The pacing of the intro\nthe type on the title cards\nand the sound design"),
            ("lines-6", "https://www.youtube.com/watch?v=demo", "Alpha launch film",
             (1...6).map { "A thought, line \($0)" }.joined(separator: "\n")),
            ("youtube", "https://www.youtube.com/watch?v=demo", "Alpha launch film", ""),
            ("pinterest", "https://www.pinterest.com/pin/1234/", "Reading nook with warm light", ""),
            ("github", "https://github.com/alpha-example/beta-sync", "alpha-example/beta-sync: a local sync engine", ""),
        ]
        for scheme in [ColorScheme.light, .dark] {
            for shot in cases {
                let api = SuggestFakeAPI(more: bank)
                let center = await center(api)
                await center.noticed(look(shot.url, title: shot.title), live: true)
                try await waitForSuggestions(center)
                if !shot.text.isEmpty { center.send(.draftChanged(shot.text)) }
                let notch = SaveWhyNotchModel()
                notch.collapsed = SaveWhyNotch.collapsed(notch: CGRect(x: 0, y: 0, width: 185, height: 32))
                notch.band = 32
                notch.grown = true
                let name = "\(shot.name)-\(scheme == .dark ? "dark" : "light").png"
                try render(SaveWhyPanelView(center: center, focus: SaveWhyFocus(), notch: notch), scheme: scheme,
                           to: base.appendingPathComponent(name))
            }
        }
    }

    private func render(_ view: some View, scheme: ColorScheme, to url: URL) throws {
        // The panel is notch black in both appearances and draws AppKit's own field dark (`darkAqua`, as the live
        // panel sets it); only the desktop behind it follows the appearance.
        let desktop = scheme == .dark ? Color(white: 0.12) : Color(white: 0.93)
        let root = view
            .frame(width: SaveWhyPanelView.width + 2 * SaveWhyNotch.ear + 80, height: 360, alignment: .top)
            .background(desktop)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: CGSize(width: SaveWhyPanelView.width + 2 * SaveWhyNotch.ear + 80,
                                                        height: 360))
        host.appearance = NSAppearance(named: .darkAqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.6))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        try XCTUnwrap(rep.representation(using: .png, properties: [:])).write(to: url)
    }
}

private actor SuggestFakeAPI: SavedWhyAPI {
    let more: [SavedWhyOptions.Reason]
    let scores: [String: Double]?
    let delay: TimeInterval
    var posts: [(url: String, answer: SavedWhyAnswer)] = []
    var edits: [(url: String, at: String, answer: SavedWhyAnswer)] = []
    var suggestAsked: [String] = []

    init(more: [SavedWhyOptions.Reason], scores: [String: Double]? = nil, delay: TimeInterval = 0) {
        self.more = more
        self.scores = scores
        self.delay = delay
    }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }

    func savedWhyOptions() async throws -> SavedWhyOptions {
        var options = SavedWhyOptions.basic
        options.more = more
        return options
    }

    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {
        posts.append((url, answer))
    }

    func editSavedWhy(url: String, at: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        edits.append((url, at, answer))
        return SavedWhyReply(savedWhy: SavedWhyRecord(reasons: answer.reasons))
    }

    /// The backend's answer: `basis: none` (no model installed) unless the test gives scores.
    func savedWhySuggest(url: String, title: String) async throws -> SavedWhyModelScores {
        suggestAsked.append(url)
        if delay > 0 { try await Task.sleep(for: .seconds(delay)) }
        guard let scores else { return SavedWhyModelScores() }
        return SavedWhyModelScores(basis: "model", scores: scores.map { .init(key: $0.key, score: $0.value) })
    }
}

private final class SuggestTick: @unchecked Sendable {
    private var t: TimeInterval = 1_000
    func next() -> TimeInterval { t += 1; return t }
}

private final class SuggestClock: @unchecked Sendable {
    var now: TimeInterval = 100
}
