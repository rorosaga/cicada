import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// 2026-10-19 — the "What made you save this?" panel, round 6 (owner, with a screenshot of the panel beside Chrome's
/// own "Edit bookmark" bubble):
///
/// 1. "The four options could all fit on a single line."
/// 2. "I bookmarked a website, explained what interested me, and pressed anywhere else on the screen (not the Done
///    button). In Cicada I see that it didn't save" — an answer is never lost to a click elsewhere, Esc or focus moving
///    away; it is attached once a sync confirms the bookmark.
/// 3. "Touching the star, even if it's already bookmarked, keeps prompting me … It should just put the same Cicada
///    prompt, but with the text already filled in or the selection already made if I already did it."
/// 4. "I use Wispr Flow a lot for dictation … I selected the text box and was dictating and it went away." — once the
///    person clicks into the field (or taps a chip) only they close it.
///
/// Synthetic bookmarks only; nothing reads a browser.
@MainActor
final class SaveWhyKeepsTests: XCTestCase {
    private let channel = "chrome-bookmarks"
    private let link = "https://alpha.example/post"
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
    }

    private func center(_ api: KeepsFakeAPI, presenter: (any SaveWhyPresenting)? = nil) -> SaveWhyCenter {
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        // Each reading of the clock is a second later, so no input falls inside `armDelay` of the panel showing.
        let tick = Tick()
        return SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, uptime: { tick.next() })
    }

    private func named(_ url: String? = nil) -> FreshBookmark {
        FreshBookmark(url: url ?? link, title: "Alpha post", origin: "chrome-bookmark", channel: channel,
                      addedAt: ISO8601DateFormatter().string(from: Date()))
    }

    private func look(_ items: [FreshBookmark], firstSync: Bool = false) -> BookmarkSyncResult {
        var r = BookmarkSyncResult(new: 0, skipped: 1, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: channel, found: 2, new: 0, skipped: 1,
                                      firstSync: firstSync)])
        r.fresh = items
        r.freshTotal = items.count
        return r
    }

    /// What the person gives, four ways.
    private enum Given: CaseIterable { case chips, words, both, nothing }

    private func give(_ given: Given, to center: SaveWhyCenter) -> SavedWhyAnswer? {
        switch given {
        case .chips:
            center.input(.tapReason("design"))
            center.input(.tapReason("someday"))
            return SavedWhyAnswer(reasons: ["design", "someday"])
        case .words:
            center.input(.engage)
            center.send(.draftChanged("their pricing table"))
            return SavedWhyAnswer(text: "their pricing table")
        case .both:
            center.input(.tapReason("product"))
            center.input(.engage)
            center.send(.draftChanged("the onboarding"))
            return SavedWhyAnswer(reasons: ["product"], text: "the onboarding")
        case .nothing:
            return nil
        }
    }

    /// The three ways a panel is dismissed without Save.
    private enum Leave: CaseIterable { case clickElsewhere, escape, focusLostThenClick }

    private func leave(_ how: Leave, _ center: SaveWhyCenter) {
        switch how {
        case .clickElsewhere: center.click(at: CGPoint(x: 5, y: 900))
        case .escape: center.send(.escape)
        case .focusLostThenClick:
            // Another app's window takes the keyboard (a dictation overlay) and the question's timer runs out: a
            // touched panel stays…
            let touched = center.state?.engaged == true
            center.send(.timeout)
            if touched { XCTAssertTrue(center.isShowing, "focus loss never closes a touched panel") }
            // …until the person clicks elsewhere.
            center.click(at: CGPoint(x: 5, y: 900))
        }
    }

    // MARK: - 1. One line

    /// The four reasons sit on one line at the panel's width at 1×, and wrap into two balanced rows (never three and
    /// one) when a larger text size leaves no room — measured on the real chips, not an estimate.
    func testTheFourReasonsFitOnOneLineAndWrapGracefullyAtLargeText() {
        let saved = ThemeStore.shared.uiScale
        defer { ThemeStore.shared.uiScale = saved }
        func height(at scale: Double) -> (CGFloat, CGFloat) {
            ThemeStore.shared.uiScale = scale
            let chips = SaveWhyReasonChips(reasons: SavedWhyOptions.basic.reasons, isSelected: { _ in false },
                                           onTap: { _ in })
            let row = NSHostingView(rootView: chips.frame(width: SaveWhyPanelView.contentWidth))
            let one = NSHostingView(rootView: SaveWhyReasonChips(reasons: [SavedWhyOptions.basic.reasons[0]],
                                                                 isSelected: { _ in false }, onTap: { _ in }))
            return (row.fittingSize.height, one.fittingSize.height)
        }
        let (atOne, chipAtOne) = height(at: 1.0)
        XCTAssertEqual(atOne, chipAtOne, accuracy: 0.5, "one line at 1×")
        let (large, chipLarge) = height(at: 1.4)
        XCTAssertEqual(large, 2 * chipLarge + CicadaTheme.scaled(6), accuracy: 1, "two rows at 1.4×")

        XCTAssertEqual(SaveWhyPanelLayout.rows(widths: [90, 95, 100, 115], available: 436, spacing: 6), [[0, 1, 2, 3]])
        XCTAssertEqual(SaveWhyPanelLayout.rows(widths: [130, 135, 140, 160], available: 436, spacing: 6),
                       [[0, 1], [2, 3]], "balanced, never three and one")
        XCTAssertEqual(SaveWhyPanelLayout.rows(widths: [300, 300], available: 436, spacing: 6), [[0], [1]])
        XCTAssertEqual(SaveWhyPanelLayout.rows(widths: [], available: 436, spacing: 6), [])
    }

    // MARK: - 2. A dismissal never loses the answer

    /// A confirmed panel, every way of leaving, every kind of answer: what was given is posted once; nothing given
    /// writes nothing.
    func testLeavingAConfirmedPanelKeepsWhatWasGiven() async {
        for how in Leave.allCases { for given in Given.allCases {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let center = center(api)
            await center.noticed(look([named()]), live: true)
            let answer = give(given, to: center)
            leave(how, center)
            await center.settle()
            XCTAssertFalse(center.isShowing, "\(how) closes it")
            let posts = await api.posts
            XCTAssertEqual(posts.map(\.answer), answer.map { [$0] } ?? [], "\(how), \(given)")
        } }
    }

    /// The owner's case. The person answers on a panel the backend has not confirmed yet and leaves; the confirmation
    /// does not come in time (a sync refused while Sleep writes never confirms). Before: the answer lived only in
    /// memory and was dropped at `confirmBound`. Now it is held, awaiting its browser's sync, never posted before one
    /// lands — and posted when one does.
    func testAnAnswerGivenBeforeTheBackendAgreesIsKeptUntilItsSyncLands() async {
        for how in Leave.allCases { for given in Given.allCases where given != .nothing {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let center = center(api)
            center.bubbleSeen(channel: channel)
            center.candidate(named())              // the app's diff of Chrome's file names the link
            let answer = give(given, to: center)
            leave(how, center)
            center.withdraw(reason: "no confirmation in time")   // what the bound's timer does
            await center.settle()
            var posts = await api.posts
            XCTAssertTrue(posts.isEmpty, "never posted before a sync confirms it (\(how), \(given))")
            XCTAssertEqual(center.heldCount, 1, "held, not dropped (\(how), \(given))")
            XCTAssertEqual(SaveWhyOutbox(defaults: defaults).entries.first?.isAwaiting, true)
            await center.retryHeld()                // Sleep let go, the app relaunched: still awaiting its sync
            posts = await api.posts
            XCTAssertTrue(posts.isEmpty)

            // The catch-up sync lands (not live, no early look): the answer goes.
            await center.syncLanded(look([]))
            posts = await api.posts
            XCTAssertEqual(posts.map(\.url), [link])
            XCTAssertEqual(posts.map(\.answer), [answer!])
            XCTAssertEqual(center.heldCount, 0)
        } }
    }

    /// A sync that lands before the link is saved (it read the file first) gets a 404 for it: held for the next sync,
    /// never dropped (before: a 404 dropped a held answer for good).
    func testANotSavedYetAnswerWaitsForTheNextSync() async {
        let api = KeepsFakeAPI()
        await api.fail(with: [APIError.httpError(404, "That link isn't saved yet")])
        let center = center(api)
        await center.noticed(look([named()]), live: true, early: 1)
        center.input(.tapReason("read_later"))
        center.input(.clickOutside)
        await center.settle()
        XCTAssertEqual(center.heldCount, 1)
        await center.syncLanded(look([]))
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["read_later"])])
        XCTAssertEqual(center.heldCount, 0)
    }

    /// An old held answer (an app from before this change) still decodes and goes out.
    func testAnAnswerHeldByAnOlderAppStillDecodes() throws {
        let old = #"[{"url":"https://alpha.example/post","answer":{"reasons":["design"]},"at":800000000}]"#
        defaults.set(Data(old.utf8), forKey: SaveWhyOutbox.key)
        let entries = SaveWhyOutbox(defaults: defaults).entries
        XCTAssertEqual(entries.count, 1)
        XCTAssertFalse(entries[0].isAwaiting)
        XCTAssertNil(entries[0].editAt)
    }

    // MARK: - 4. Only the person closes a touched panel (dictation)

    /// Click into the field and dictate: no timer, no missing confirmation and no other window taking the keyboard
    /// closes the panel; the words arrive at once when the dictation is done, and leaving keeps them.
    func testAFieldClickedIntoStaysThroughDictationAndKeepsTheWords() async {
        let api = KeepsFakeAPI()
        let center = center(api)
        center.bubbleSeen(channel: channel)
        center.input(.engage)                                  // the person clicked the text box
        XCTAssertTrue(center.state?.isWriting == true, "dictating: nothing replaces the panel")
        center.send(.timeout)                                   // the question's own timer
        center.withdraw(reason: "no confirmation in time")     // the pending bound
        XCTAssertTrue(center.isShowing, "still there while the person speaks")
        center.candidate(named())
        center.send(.draftChanged("a long thought about the layout"))   // dictation pastes it all at once
        await center.noticed(look([named()]), live: true, early: 1)
        XCTAssertTrue(center.isShowing)
        center.click(at: CGPoint(x: 5, y: 900))
        await center.settle()
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(text: "a long thought about the layout")])
    }

    /// The live panel: another app's floating window taking the keyboard (a dictation overlay) never closes it; a
    /// click elsewhere does, and keeps the words.
    func testLosingTheKeyboardToAnotherWindowNeverClosesThePanel() async throws {
        let api = KeepsFakeAPI()
        let controller = SaveWhyPanelController()
        let center = center(api, presenter: controller)
        await center.noticed(look([named()]), live: true)
        let panel = try XCTUnwrap(controller.window)
        center.input(.engage)
        center.send(.draftChanged("spoken words"))
        panel.resignKey()
        let overlay = NSPanel(contentRect: CGRect(x: 0, y: 0, width: 200, height: 40),
                              styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
        overlay.level = .floating
        overlay.orderFrontRegardless()
        defer { overlay.orderOut(nil) }
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertTrue(center.isShowing)
        XCTAssertNotNil(controller.window)
        center.click(at: CGPoint(x: 5, y: 900))
        await center.settle()
        XCTAssertNil(controller.window)
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(text: "spoken words")])
    }

    /// The panel the person clicked into is the key window — Cicada stays inactive, nothing of Cicada's comes forward
    /// — so typing and dictation land in the field; Save, Return and Esc hand the keyboard back to the browser, a
    /// click elsewhere leaves it where the person put it.
    func testClickingIntoTheFieldMakesThePanelKeyAndClosingGivesTheKeyboardBack() async throws {
        for (leave, givesBack) in [(SaveWhyPanelState.Event.escape, true), (.submit, true), (.clickOutside, false)] {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let controller = SaveWhyPanelController()
            var given: [pid_t] = []
            controller.frontmostPID = { 4242 }
            controller.giveBack = { given.append($0) }
            let center = center(api, presenter: controller)
            await center.noticed(look([named()]), live: true)
            let panel = try XCTUnwrap(controller.window)
            controller.focusText()
            XCTAssertFalse(panel.isKeyWindow, "never key before the person's click inside")

            let click = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: CGPoint(x: 20, y: 20),
                                                         modifierFlags: [], timestamp: 0,
                                                         windowNumber: panel.windowNumber, context: nil,
                                                         eventNumber: 0, clickCount: 1, pressure: 1))
            panel.sendEvent(click)
            center.input(.engage)
            let wasActive = NSApplication.shared.isActive
            controller.focusText()
            XCTAssertTrue(panel.isKeyWindow, "the field's panel takes the keyboard")
            // Cicada's part never activates the app (the panel is non-activating; focusText only makes it key), so the
            // browser stays the active app and no other Cicada window comes forward. (A synthetic click in a test
            // process with no launched app flips `isActive` by itself; the real window server does not.)
            XCTAssertEqual(NSApplication.shared.isActive, wasActive, "focusing the field activates nothing")
            XCTAssertTrue(panel.styleMask.contains(.nonactivatingPanel))
            XCTAssertFalse(panel.canBecomeMain, "and no Cicada window becomes main")
            XCTAssertEqual(controller.returnTo, 4242, "the browser it took the keyboard from")

            // The field holds the focus inside the key panel, which is what an inserter asking Accessibility for the
            // focused element reaches (system-wide: the key window's app, then its focused element).
            for _ in 0..<40 where !(panel.firstResponder is NSTextView) {
                try await Task.sleep(for: .milliseconds(10))
            }
            XCTAssertTrue(panel.firstResponder is NSTextView, "the field is being edited")
            // What an inserter reaches through Accessibility is the key window's focused element — the field, as the
            // panel and the app both answer in-process. (The system-wide query is not run here: it would read which app
            // the person has in front on a shared Mac.)
            let focused = panel.accessibilityFocusedUIElement as? NSAccessibilityProtocol
            XCTAssertEqual(focused?.accessibilityRole(), .textField)
            XCTAssertEqual((NSApplication.shared.accessibilityFocusedUIElement as? NSAccessibilityProtocol)?
                .accessibilityRole(), .textField)

            center.send(.draftChanged("spoken words"))
            if leave == .clickOutside { center.click(at: CGPoint(x: 5, y: 900)) } else { center.send(leave) }
            await center.settle()
            XCTAssertNil(controller.window)
            XCTAssertEqual(given, givesBack ? [4242] : [], "\(leave)")
            let posts = await api.posts
            XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(text: "spoken words")], "\(leave) keeps the words")
            panel.orderOut(nil)
        }
    }

    /// A click inside Chrome's own bookmark bubble is the person working there, not leaving; one that closed the
    /// bubble leaves too. Done and Remove look the same from bounds, so the answer waits to learn which: no removal in
    /// the file (Done writes nothing) sends it; a removal (Remove) drops it.
    func testAClickInsideChromesBubbleIsNotLeavingUnlessItClosedIt() async throws {
        let api = KeepsFakeAPI()
        let center = center(api)
        center.removalWait = 0.1
        var bubbleShows = true
        var looks = 0
        center.bubbleOpen = { looks += 1; return bubbleShows }
        let bubble = CGRect(x: 1000, y: 80, width: 448, height: 224)
        center.bubbleSeen(channel: channel, frame: bubble)
        center.candidate(named())
        await center.noticed(look([named()]), live: true, early: 1)
        center.input(.tapReason("design"))
        center.click(at: CGPoint(x: 1100, y: 150))              // into the bubble's name field
        try await Task.sleep(for: .seconds(SaveWhyPolicy.bubbleCloseCheck + 0.15))
        XCTAssertTrue(center.isShowing, "working in Chrome's bubble keeps the panel")
        XCTAssertEqual(looks, 1, "one look, right after the click")
        bubbleShows = false
        center.click(at: CGPoint(x: 1400, y: 280))              // Done
        try await Task.sleep(for: .seconds(SaveWhyPolicy.bubbleCloseCheck + 0.05))
        XCTAssertFalse(center.isShowing, "the bubble closed, and the panel with it")
        var posts = await api.posts
        XCTAssertTrue(posts.isEmpty, "held until the file says Done or Remove")
        try await Task.sleep(for: .seconds(0.3))                // no removal came: it was Done
        await center.settle()
        posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["design"])])
    }

    /// Review 2026-10-19 — Remove pressed inside Chrome's bubble: the panel closes with the bubble, and once Chrome's
    /// file shows the bookmark gone the answer is dropped, never posted — confirmed, unconfirmed or an edit alike.
    func testRemoveInsideTheBubbleNeverPostsTheAnswer() async throws {
        for kind in ["confirmed", "unconfirmed", "edit"] {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let bubble = CGRect(x: 1000, y: 80, width: 448, height: 224)
            let center: SaveWhyCenter
            if kind == "edit" {
                center = try await openOnSaved(api, answer: SavedWhyAnswer(reasons: ["design"]))
                center.bubbleSeen(channel: channel, frame: bubble)   // a second star click: the same panel
            } else {
                center = self.center(api)
                center.bubbleSeen(channel: channel, frame: bubble)
                center.candidate(named())
                if kind == "confirmed" { await center.noticed(look([named()]), live: true, early: 1) }
            }
            center.removalWait = 0.2
            center.bubbleOpen = { false }
            center.input(.tapReason("product"))
            center.click(at: CGPoint(x: 1050, y: 280))          // Remove
            try await Task.sleep(for: .seconds(SaveWhyPolicy.bubbleCloseCheck + 0.05))
            XCTAssertFalse(center.isShowing, kind)
            center.bookmarkRemoved(on: channel)                  // Chrome writes the file without it
            await center.syncLanded(look([]))
            try await Task.sleep(for: .seconds(0.3))
            await center.settle()
            let posts = await api.posts, edits = await api.edits
            XCTAssertTrue(posts.isEmpty && edits.isEmpty, "\(kind): a removed bookmark's answer is never sent")
            XCTAssertEqual(center.heldCount, 0, kind)
        }
    }

    // MARK: - Review 2026-10-19

    /// The blocker: an answer given on the pending panel (Chrome's bubble seen, its file not written yet) and the panel
    /// closed before the diff named the link. Both orders the reviewer probed now post it once its sync lands.
    func testAPendingAnswerClosedBeforeTheFileIsKeptInBothOrders() async {
        for order in ["confirmed", "unconfirmed in time"] {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let center = center(api)
            center.bubbleSeen(channel: channel)
            center.input(.tapReason("design"))
            center.input(.clickOutside)                          // closed with no link named yet
            center.candidate(named())                            // Chrome writes; the diff names it
            if order == "confirmed" {
                await center.noticed(look([named()]), live: true, early: 1)
            } else {
                center.withdraw(reason: "no confirmation in time")
            }
            await center.settle()
            await center.syncLanded(look([]))
            let posts = await api.posts
            XCTAssertEqual(posts.map(\.url), [link], order)
            XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["design"])], order)
            XCTAssertEqual(center.heldCount, 0, order)
        }
    }

    /// The split-brain rule: a held answer carries the memory it was given in and goes only while that memory is
    /// active.
    func testAHeldAnswerGoesOnlyToTheMemoryItWasGivenIn() async {
        let api = KeepsFakeAPI()
        await api.fail(with: [APIError.httpError(409, "{\"code\":\"sleep_writing\"}")])
        let center = center(api)
        var bank = "alpha-memory"
        center.activeBank = { bank }
        await center.noticed(look([named()]), live: true)
        center.input(.tapReason("someday"))
        center.input(.clickOutside)
        await center.settle()
        XCTAssertEqual(SaveWhyOutbox(defaults: defaults).entries.first?.bank, "alpha-memory")
        bank = "beta-memory"
        await center.retryHeld()
        var posts = await api.posts
        XCTAssertTrue(posts.isEmpty, "never sent while another memory is active")
        bank = "alpha-memory"
        await center.retryHeld()
        posts = await api.posts
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["someday"])])
    }

    /// A 404 on an edit is final: the answer it names is gone, and no sync brings it back.
    func testANotFoundEditIsNotRetried() async throws {
        let api = KeepsFakeAPI()
        let center = try await openOnSaved(api, answer: SavedWhyAnswer(reasons: ["design"]))
        await api.fail(with: [APIError.httpError(404, "There's no answer from that time to change")])
        center.input(.tapReason("read_later"))
        center.input(.clickOutside)
        await center.settle()
        XCTAssertEqual(center.heldCount, 0)
        XCTAssertEqual(SaveWhyOutbox.verdict(for: APIError.httpError(404, ""), editing: true), .drop)
    }

    // MARK: - 3. The star on a page already saved

    private func existing(answer: SavedWhyAnswer?) -> ExistingBookmark {
        let item = FreshBookmark(url: link, title: "Alpha post", origin: "chrome-bookmark", channel: channel,
                                 addedAt: "2026-10-18T09:00:00+00:00")
        return ExistingBookmark(item: item, answer: answer, at: answer == nil ? nil : "2026-10-18T09:00:05+00:00")
    }

    private func openOnSaved(_ api: KeepsFakeAPI, answer: SavedWhyAnswer?, presenter: KeepsPresenter? = nil)
        async throws -> SaveWhyCenter {
        let center = center(api, presenter: presenter)
        let found = existing(answer: answer)
        center.existing = { _ in found }
        center.bubbleSeen(channel: channel)
        for _ in 0..<50 where center.state?.isPending != false { try await Task.sleep(for: .milliseconds(5)) }
        return center
    }

    /// The panel opens filled in with the saved answer (taps and words); leaving unchanged writes nothing, a change
    /// edits that answer — never a new answer, never a second save.
    func testTheStarOnASavedPageOpensItsAnswerFilledInForEditing() async throws {
        let said = SavedWhyAnswer(reasons: ["design", "someday"], text: "their onboarding")
        // Unchanged: nothing written, however it is left.
        for how in Leave.allCases {
            defaults = UserDefaults(suiteName: "SaveWhyKeepsTests.\(UUID().uuidString)")!
            let api = KeepsFakeAPI()
            let center = try await openOnSaved(api, answer: said)
            XCTAssertTrue(center.confirmed, "a bookmark Cicada holds needs no confirmation")
            XCTAssertTrue(center.state?.isEditing == true)
            XCTAssertEqual(center.state?.selection, said, "filled in")
            XCTAssertEqual(center.state?.draft, "their onboarding")
            leave(how, center)
            await center.settle()
            let posts = await api.posts, edits = await api.edits
            XCTAssertTrue(posts.isEmpty && edits.isEmpty, "unchanged writes nothing (\(how))")
            XCTAssertEqual(center.lastOutcome, .unchanged)
        }
        // The question's own timer on an untouched filled-in panel: nothing written either.
        let idleAPI = KeepsFakeAPI()
        let idle = try await openOnSaved(idleAPI, answer: said)
        idle.send(.timeout)
        await idle.settle()
        let idlePosts = await idleAPI.posts, idleEdits = await idleAPI.edits
        XCTAssertTrue(idlePosts.isEmpty && idleEdits.isEmpty)

        // Changed: one edit of that answer, by its time; no post.
        let api = KeepsFakeAPI()
        let presenter = KeepsPresenter()
        let center = try await openOnSaved(api, answer: said, presenter: presenter)
        center.input(.tapReason("someday"))
        center.input(.tapReason("read_later"))
        center.input(.engage)
        center.send(.draftChanged("their onboarding and pricing"))
        center.bubbleSeen(channel: channel)                     // a second star click while it is open
        XCTAssertEqual(presenter.shown, 1, "one panel")
        center.withdraw(reason: "no confirmation in time")      // no bookmark ever comes: Chrome wrote nothing
        XCTAssertTrue(center.isShowing)
        center.click(at: CGPoint(x: 5, y: 900))
        await center.settle()
        let posts = await api.posts, edits = await api.edits
        XCTAssertTrue(posts.isEmpty, "never a new answer, never a second save")
        XCTAssertEqual(edits.map(\.at), ["2026-10-18T09:00:05+00:00"])
        XCTAssertEqual(edits.map(\.answer), [SavedWhyAnswer(reasons: ["design", "read_later"],
                                                            text: "their onboarding and pricing")])
    }

    /// What the saved answer holds that the panel does not show (a retired reason, a project) survives an edit.
    func testAnEditKeepsWhatThePanelDoesNotShow() {
        var s = SaveWhyPanelState(editing: named(), answer: SavedWhyAnswer(reasons: ["design", "technique"],
                                                                           project: "alpha-project", text: nil),
                                  at: "2026-10-18T09:00:05+00:00", order: SavedWhyOptions.basic.reasons.map(\.key))
        XCTAssertTrue(s.isSelected(reason: "design"))
        XCTAssertEqual(s.send(.escape), [.close], "unchanged")
        var changed = SaveWhyPanelState(editing: named(), answer: SavedWhyAnswer(reasons: ["technique"],
                                                                                 project: "alpha-project"),
                                        at: "t0", order: SavedWhyOptions.basic.reasons.map(\.key))
        _ = changed.send(.tapReason("product"))
        XCTAssertEqual(changed.send(.clickOutside),
                       [.edit(SavedWhyAnswer(reasons: ["product", "technique"], project: "alpha-project"), at: "t0"),
                        .close])
        var emptied = SaveWhyPanelState(editing: named(), answer: SavedWhyAnswer(reasons: ["design"]), at: "t0",
                                        order: SavedWhyOptions.basic.reasons.map(\.key))
        _ = emptied.send(.tapReason("design"))
        XCTAssertEqual(emptied.send(.submit), [.close], "an emptied answer is never written as a deletion")
    }

    /// A saved bookmark never answered: the panel asks as usual, bound to that save, and posts one first answer for
    /// it (its own moment of saving) — never a second save.
    func testTheStarOnASavedPageWithNoAnswerAsksForThatSave() async throws {
        let api = KeepsFakeAPI()
        let center = try await openOnSaved(api, answer: nil)
        XCTAssertFalse(center.state?.isEditing == true)
        XCTAssertTrue(center.confirmed)
        center.input(.tapReason("product"))
        center.input(.clickOutside)
        await center.settle()
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.url), [link])
        XCTAssertEqual(posts.map(\.addedAt), ["2026-10-18T09:00:00+00:00"], "that save's own moment")
    }

    /// Removing the bookmark in Chrome's bubble: the existing removal path — the pending panel withdraws, keeping
    /// nothing, even when touched.
    func testRemovePressedInChromesBubbleKeepsNothing() async throws {
        let api = KeepsFakeAPI()
        let center = center(api)
        center.bubbleSeen(channel: channel)
        center.input(.tapReason("design"))
        center.bookmarkRemoved(on: channel)
        XCTAssertFalse(center.isShowing)
        XCTAssertEqual(center.lastOutcome, .withdrawn)
        await center.settle()
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty)
        XCTAssertEqual(center.heldCount, 0)

        // The star on a saved page, a change, then Remove: nothing is written from the panel.
        let savedAPI = KeepsFakeAPI()
        let saved = try await openOnSaved(savedAPI, answer: SavedWhyAnswer(reasons: ["design"]))
        saved.input(.tapReason("product"))
        saved.bookmarkRemoved(on: channel)
        XCTAssertFalse(saved.isShowing)
        await saved.settle()
        let savedPosts = await savedAPI.posts, savedEdits = await savedAPI.edits
        XCTAssertTrue(savedPosts.isEmpty && savedEdits.isEmpty)
    }

    /// Which saved bookmark the star was on: only one Chrome's file held before the click and Cicada holds as that
    /// browser's, matched exactly.
    func testTheSavedBookmarkIsFoundOnlyExactlyAndOnlyIfTheBrowserHeldIt() throws {
        func item(_ json: [String: Any]) throws -> MediaFeedItem {
            var base: [String: Any] = ["mediaEntityId": "media-x", "url": "https://alpha.example/post",
                                       "title": "Alpha post", "mediaType": "url", "savedAt": "2026-10-01T10:00:00Z",
                                       "origin": "chrome-bookmark", "lastSavedAt": "2026-10-18T09:00:00Z"]
            base.merge(json) { $1 }
            return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: base))
        }
        let answered = try item(["savedWhy": ["reasons": ["design"], "labels": ["The design"], "text": "the type",
                                              "at": "2026-10-18T09:00:05Z", "addedAt": "2026-10-18T09:00:00Z"]])
        let holds: Set<String> = [link]
        let found = try XCTUnwrap(ExistingBookmark.find(url: link, channel: channel, items: [answered],
                                                        browserHolds: holds))
        XCTAssertEqual(found.answer, SavedWhyAnswer(reasons: ["design"], text: "the type"))
        XCTAssertEqual(found.at, "2026-10-18T09:00:05Z")
        XCTAssertEqual(found.item.addedAt, "2026-10-18T09:00:00Z")
        XCTAssertNil(ExistingBookmark.find(url: link, channel: channel, items: [answered], browserHolds: []),
                     "a link Chrome did not hold before the click is a new bookmark")
        XCTAssertNil(ExistingBookmark.find(url: link, channel: channel, items: [answered], browserHolds: nil))
        XCTAssertNil(ExistingBookmark.find(url: link + "/", channel: channel, items: [answered],
                                           browserHolds: [link + "/"]), "never a near match")
        let safari = try item(["origin": "safari-bookmark"])
        XCTAssertNil(ExistingBookmark.find(url: link, channel: channel, items: [safari], browserHolds: holds))
        let unanswered = try XCTUnwrap(ExistingBookmark.find(url: link, channel: channel, items: [try item([:])],
                                                             browserHolds: holds))
        XCTAssertNil(unanswered.answer)
        XCTAssertEqual(unanswered.item.addedAt, "2026-10-18T09:00:00Z")
    }

    /// The front tab's link: only an http(s) answer; a refusal or a timeout is nothing.
    func testTheFrontTabAnswerIsALinkOrNothing() async {
        let ok = await ChromeFrontTab.url(bundleId: "com.google.Chrome") { script in
            XCTAssertTrue(script.contains("URL of active tab of front window"))
            return ChildProcess.Output(status: 0, stdout: "https://alpha.example/post\n", stderr: "")
        }
        XCTAssertEqual(ok, "https://alpha.example/post")
        let refused = await ChromeFrontTab.url(bundleId: "com.google.Chrome") { _ in
            ChildProcess.Output(status: 1, stdout: "", stderr: "execution error: Not authorized (-1743)")
        }
        XCTAssertNil(refused)
        let other = await ChromeFrontTab.url(bundleId: "com.google.Chrome") { _ in
            ChildProcess.Output(status: 0, stdout: "chrome://newtab/", stderr: "")
        }
        XCTAssertNil(other)
    }
}

// MARK: - Fakes

private actor KeepsFakeAPI: SavedWhyAPI {
    var posts: [(url: String, answer: SavedWhyAnswer, addedAt: String?)] = []
    var edits: [(url: String, at: String, answer: SavedWhyAnswer)] = []
    var failures: [Error] = []
    func fail(with errors: [Error]) { failures = errors }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }

    func savedWhyOptions() async throws -> SavedWhyOptions { .basic }

    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {
        if !failures.isEmpty { throw failures.removeFirst() }
        posts.append((url, answer, addedAt))
    }

    func editSavedWhy(url: String, at: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        if !failures.isEmpty { throw failures.removeFirst() }
        edits.append((url, at, answer))
        return SavedWhyReply(savedWhy: SavedWhyRecord(reasons: answer.reasons, text: answer.text, at: at))
    }
}

private final class Tick: @unchecked Sendable {
    private var t: TimeInterval = 1_000
    func next() -> TimeInterval { t += 1; return t }
}

@MainActor
private final class KeepsPresenter: SaveWhyPresenting {
    var shown = 0
    var hidden = 0
    func show(_ center: SaveWhyCenter) { shown += 1 }
    func hide() { hidden += 1 }
    func focusText() {}
}
