import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner ruling 2026-10-14, "Graduate + Needs you first", and the Home design review's #1–#11 — the graduation rule,
/// the order, the empty page, the hit targets and the words, as pure rules and source checks (`HomeLayoutTests`'
/// pattern). Synthetic values only.
@MainActor
final class HomeFrontDoorTests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func row(_ id: String, _ kind: SourceKind, episodes: Int = 0, entities: Int = 0) -> SourceOverview {
        SourceOverview(id: id, label: id, kind: kind, episodes: episodes, entities: entities)
    }

    private func gsRow(_ key: String, _ state: FoundRowState) -> GettingStartedRow {
        GettingStartedRow(id: FoundItemID(key: key)!, title: key, detail: "", state: state)
    }

    // MARK: The graduation signal

    func testChatsInMemoryIsAConversationSourceThatFedAPage() {
        XCTAssertNil(HomeSetup.hasChatsInMemory(nil), "unknown is never an answer")
        XCTAssertEqual(HomeSetup.hasChatsInMemory([]), false)
        XCTAssertEqual(HomeSetup.hasChatsInMemory([row("chat-export:chatgpt", .harness, episodes: 40, entities: 0)]),
                       false, "captured but never read is not in memory yet")
        XCTAssertEqual(HomeSetup.hasChatsInMemory([row("chat-export:chatgpt", .harness, episodes: 40, entities: 12)]),
                       true, "an imported export that fed pages")
        XCTAssertEqual(HomeSetup.hasChatsInMemory([row("harness:claude-code", .harness, episodes: 3, entities: 2)]),
                       true, "a connected agent's conversations count too")
        XCTAssertEqual(HomeSetup.hasChatsInMemory([row("chrome-bookmarks", .browser, episodes: 900, entities: 300)]),
                       false, "bookmarks are not chats")
    }

    func testAVendorIsNotAskedAgainOnceItsExportIsIn() {
        XCTAssertEqual(HomeSetup.vendorsToAsk(nil), ChatVendor.allCases, "unknown keeps the offer")
        XCTAssertEqual(HomeSetup.vendorsToAsk([row("chat-export:chatgpt", .harness, episodes: 5)]), [.claude, .gemini])
        XCTAssertEqual(HomeSetup.vendorsToAsk([row("chat-export:claude", .harness, episodes: 0)]), ChatVendor.allCases,
                       "a row with no episodes is not an import")
    }

    func testThingsLeftCountsOnlyWhatThePersonCanDo() {
        let rows = [gsRow("agent:claude-code", .on), gsRow("agent:codex", .off),
                    gsRow("browser:chrome-bookmarks", .needsAction("Allow")), gsRow("agent:cursor", .working("…")),
                    gsRow("app:notes", .failed("no"))]
        XCTAssertEqual(HomeSetup.thingsLeft(rows), 3, "off, needs action and failed; never on or in progress")
        XCTAssertEqual(HomeSetup.thingsLeft([]), 0)
    }

    // MARK: The graduation rule (fresh, mid-setup, graduated, returning with items waiting)

    func testGettingStartedGraduates() {
        // Fresh: no record (an install onboarded before Track I, or Hide pressed) — nothing.
        XCTAssertEqual(GettingStartedPresentation.of(visible: false, graduated: false, expanded: false, left: 0), .none)
        // Mid-setup, no chats in memory yet — the whole card, whatever is left.
        XCTAssertEqual(GettingStartedPresentation.of(visible: true, graduated: false, expanded: false, left: 3), .card)
        XCTAssertEqual(GettingStartedPresentation.of(visible: true, graduated: false, expanded: false, left: 0), .card)
        // Graduated with nothing left — it retires itself.
        XCTAssertEqual(GettingStartedPresentation.of(visible: true, graduated: true, expanded: false, left: 0), .none)
        // Graduated with things left — one line.
        XCTAssertEqual(GettingStartedPresentation.of(visible: true, graduated: true, expanded: false, left: 2),
                       .line(left: 2))
        // Its viewer opened it (or Settings' *Show setup checklist* did) — the whole card again.
        XCTAssertEqual(GettingStartedPresentation.of(visible: true, graduated: true, expanded: true, left: 0), .card)
        // Hidden stays hidden, graduated or not.
        XCTAssertEqual(GettingStartedPresentation.of(visible: false, graduated: true, expanded: true, left: 2), .none)
    }

    func testHomeIsOrderedByThePersonsState() throws {
        let firstWeek = HomeArrangement.of(setupVisible: true, graduated: false)
        XCTAssertEqual(firstWeek, .firstWeek)
        XCTAssertEqual(Array(firstWeek.order.prefix(3)), [.tour, .setup, .today],
                       "setup leads the first week, under the tour offer onboarding asked for (never off-screen)")

        // Returning: graduated, or no card at all — what is waiting on the person leads, setup is last.
        for returning in [HomeArrangement.of(setupVisible: true, graduated: true),
                          HomeArrangement.of(setupVisible: false, graduated: false),
                          HomeArrangement.of(setupVisible: false, graduated: true)] {
            XCTAssertEqual(returning, .returning)
            XCTAssertEqual(returning.order.first, .needsYou, "Needs you first")
            XCTAssertEqual(returning.order.last, .setup, "the collapsed setup line sits at the foot")
        }

        for arrangement in [HomeArrangement.firstWeek, .returning] {
            let order = arrangement.order
            XCTAssertEqual(Set(order), Set(HomeBlockID.allCases), "every block once")
            XCTAssertEqual(order.count, HomeBlockID.allCases.count)
            let needsYou = try! XCTUnwrap(order.firstIndex(of: .needsYou))
            XCTAssertGreaterThan(try! XCTUnwrap(order.firstIndex(of: .tip)), needsYou, "Make it yours never above Needs you")
        }
        let returning = HomeArrangement.returning.order
        XCTAssertGreaterThan(try XCTUnwrap(returning.firstIndex(of: .tour)), try XCTUnwrap(returning.firstIndex(of: .needsYou)),
                             "for a returning person the tour offer follows Needs you")
    }

    // MARK: Empty Home (review #8)

    func testEmptyHomeSaysOneTrueThing() {
        var e = HomeEmptiness(captured: 0, waiting: 0, showsWaiting: true, needsYou: 0, inboxLoaded: true,
                              lastReadNever: true)
        XCTAssertTrue(e.allEmpty)
        XCTAssertEqual(e.mode(setupCardShown: false), .one, "one block says it once")
        XCTAssertEqual(e.mode(setupCardShown: true), .hidden, "Getting started already says nothing is there yet")

        e.captured = nil
        XCTAssertFalse(e.todayEmpty, "unknown is never empty")
        XCTAssertEqual(e.mode(setupCardShown: false), .blocks)

        e = HomeEmptiness(captured: 0, waiting: 4, showsWaiting: true, needsYou: 0, inboxLoaded: true,
                          lastReadNever: true)
        XCTAssertFalse(e.todayEmpty, "conversations waiting to be read are something")
        e.showsWaiting = false
        XCTAssertTrue(e.todayEmpty, "a waiting count Today does not show cannot fill it")

        e = HomeEmptiness(captured: 3, waiting: 0, showsWaiting: true, needsYou: 0, inboxLoaded: false,
                          lastReadNever: false)
        XCTAssertFalse(e.needsYouEmpty, "an inbox not loaded yet is not empty")
        e.inboxLoaded = true
        XCTAssertTrue(e.needsYouEmpty)
        XCTAssertEqual(e.mode(setupCardShown: false), .blocks, "only some empty: each block keeps its label")
    }

    // MARK: Hit targets (review #1, #4, #5; DR-69)

    func testALinksHitAreaIs28PointsAndLayoutNeutral() throws {
        XCTAssertEqual(HomeTargets.linkHeight, 28)
        let label = CGRect(x: 10, y: 10, width: 60, height: 15)
        let hit = LinkHitShape.hitRect(for: label, minHeight: 28, slop: 6)
        XCTAssertEqual(hit.height, 28, accuracy: 0.001)
        XCTAssertEqual(hit.width, 72, accuracy: 0.001)
        XCTAssertEqual(hit.midY, label.midY, accuracy: 0.001, "centred on the label")
        XCTAssertEqual(LinkHitShape.hitRect(for: CGRect(x: 0, y: 0, width: 40, height: 30), minHeight: 28, slop: 6).height,
                       30, "a taller label is never shrunk")

        // Layout-neutral: the link renders at its label's own height, so a sentence keeps its line.
        let link = try XCTUnwrap(ImageRenderer(content: InlineLink(title: "Open Inbox") {}.fixedSize()).nsImage)
        let text = try XCTUnwrap(ImageRenderer(content: Text("Open Inbox").font(CicadaTheme.metaMediumFont)
            .fixedSize()).nsImage)
        XCTAssertEqual(link.size.height, text.size.height, accuracy: 0.5)
    }

    func testThePillPickerIs28PointsAndRinged() throws {
        XCTAssertEqual(PillPicker<Int>.height, 28, "DR-69's target, a compact button's height")
        let picker = PillPicker(title: "Appearance", selection: .constant(AppearancePreference.system),
                                options: AppearancePreference.allCases.map { PillOption(value: $0, label: $0.label) },
                                compact: true)
        let size = try XCTUnwrap(ImageRenderer(content: picker.fixedSize()).nsImage).size
        XCTAssertEqual(size.height, CicadaTheme.scaled(28), accuracy: 0.5)

        let text = try source("Views/Common/PillPicker.swift")
        XCTAssertFalse(text.contains("CicadaTheme.border"), "DR-9 — a ring, never the opaque border")
        XCTAssertFalse(text.contains(".semibold"), "DR-16 — semibold is reserved")
        XCTAssertTrue(text.contains(".ringed(in: Capsule())"))
    }

    func testAnExportRowIsOne36PointTarget() throws {
        // The row's mark reads the Store, so the row is checked in its source rather than rendered bare.
        let rows = try source("Views/Home/HomeExportRows.swift")
        let vendorRow = try XCTUnwrap(rows.range(of: "struct ExportVendorRow").map { String(rows[$0.lowerBound...]) })
            .components(separatedBy: "struct ExportWaitRow").first ?? ""
        XCTAssertTrue(vendorRow.contains("minHeight: CicadaTheme.scaled(RowMetrics.oneLine)"), "a 36 pt row")
        XCTAssertTrue(vendorRow.contains("Button { onSeeHow(vendor) }"), "the whole row is the button")
        XCTAssertTrue(vendorRow.contains(".contentShape(Rectangle())"), "every point of the row hits")
        XCTAssertFalse(vendorRow.contains(".semibold"), "DR-16")
        XCTAssertEqual(RowMetrics.oneLine, 36)
        XCTAssertEqual(Copy.importSeeHow, "See how ›")

        let card = try source("Views/Home/GettingStartedCard.swift")
        XCTAssertFalse(card.contains("ExportAskRow("), "Home asks with onboarding's row, not Track I's")
        XCTAssertTrue(card.contains("ExportVendorRow(vendor:"))
        XCTAssertFalse(card.contains("DisclosureGroup"), "no 13 pt disclosure on Home")
        XCTAssertFalse(card.contains(".buttonStyle(.link)"), "DR-40 — four button kinds, never a bare link button")
        XCTAssertFalse(card.contains("largecircle.fill.circle"), "no 11 pt hand-rolled radios")
        let home = try source("Views/Home/HomeView.swift")
        XCTAssertTrue(home.contains("HomeWalkthroughLayer(vendor:"), "See how opens onboarding's walkthrough over Home")
    }

    func testEveryLineWithOneDestinationIsOneButton() throws {
        let sections = try source("Views/Home/HomeSections.swift")
        XCTAssertFalse(sections.contains("InlineLink(title: Copy.homeOpenSleep)"), "review #9 — no repeated Sleep ›")
        XCTAssertTrue(sections.contains("HomeRowButton(help: Copy.homeOpenSleepHelp"), "the waiting line opens Sleep")
        XCTAssertTrue(sections.contains("routeToSleepDetails(.lastCycle)"), "Last read opens that read in Details")
        XCTAssertTrue(sections.contains("HomeTargets.tagHitHeight"), "a page tag sits in a 24 pt hit frame")
        XCTAssertEqual(HomeTargets.tagHitHeight, 24)
        XCTAssertGreaterThan(HomeTargets.tagHitHeight, Tag.height)
    }

    // MARK: The Find/Ask switch (review #10)

    func testFindAndAskAreTextTabsWithNoAccentAndNoAnimation() throws {
        let body = try source("Views/Find/FindPanelBody.swift")
        XCTAssertFalse(body.contains(".pickerStyle(.segmented)"), "DR-45 — the native control paints the accent")
        XCTAssertTrue(body.contains("TextTabs(tabs: [TextTab(id: FindMode.find"))
        XCTAssertFalse(body.contains("CicadaMotion.morph"), "DR-60 — ⌘⏎ never animates the switch")
        XCTAssertFalse(body.contains(".foregroundStyle(CicadaTheme.accent)\n                .accessibilityHidden(true)\n            TextField"),
                       "the field's glyph is not one of the accent's six uses")
    }

    // MARK: Make it yours (review #4)

    func testMakeItYoursLastsOneSession() throws {
        XCTAssertTrue(AppearanceTipPolicy.visible(armed: true, dismissed: false, seenBefore: false, shownThisSession: false))
        XCTAssertTrue(AppearanceTipPolicy.visible(armed: true, dismissed: false, seenBefore: true, shownThisSession: true),
                      "the session that showed it keeps it")
        XCTAssertFalse(AppearanceTipPolicy.visible(armed: true, dismissed: false, seenBefore: true, shownThisSession: false),
                       "a later launch never shows it again")
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.tip.\(UUID().uuidString)"))
        let saved = AppearanceTipPolicy.shownThisSession
        defer { AppearanceTipPolicy.shownThisSession = saved }
        AppearanceTipPolicy.noteShown(defaults)
        XCTAssertTrue(defaults.bool(forKey: AppearanceTipPolicy.seenKey))
        XCTAssertTrue(AppearanceTipPolicy.shownThisSession)
    }

    // MARK: Setup stays reachable (owner 2026-10-14)

    func testShowSetupChecklistOpensTheWholeCard() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.gs.\(UUID().uuidString)"))
        GettingStartedState.showChecklist(bank: "alpha", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "alpha", defaults: defaults)?.expanded, true)
        GettingStartedState.setExpanded(false, bank: "alpha", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "alpha", defaults: defaults)?.expanded, false,
                       "the viewer's closed choice is remembered (DR-39)")
        GettingStartedState.record(bank: "alpha", enabled: [.browser("safari-bookmarks")], defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "alpha", defaults: defaults)?.expanded, false,
                       "an Also-on-this-Mac turn-on never reopens it")
        GettingStartedState.showChecklist(bank: "alpha", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "alpha", defaults: defaults)?.expanded, true,
                       "Settings' Show setup checklist opens it again")
        let settings = try source("Views/Settings/SettingsDemoTourGroup.swift")   // General's Getting started (B12)
        XCTAssertTrue(settings.contains("GettingStartedState.showChecklist(bank: store.bank)"))
    }

    /// Review B1 — the Welcome's record must not keep the card whole: record → chats in memory → one line → nothing.
    func testAWelcomeRecordGraduatesToALineThenLeaves() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.gs.\(UUID().uuidString)"))
        GettingStartedState.record(bank: "alpha", enabled: [.agent("codex"), .browser("safari-bookmarks")],
                                   defaults: defaults)
        let record = try XCTUnwrap(GettingStartedState.load(bank: "alpha", defaults: defaults))
        XCTAssertFalse(record.expanded, "Start records the card; it does not hold it open")
        let visible = GettingStartedProgress.visible(record: record)

        let before = HomeSetup.hasChatsInMemory([row("chat-export:claude", .harness, episodes: 30)]) == true
        XCTAssertEqual(GettingStartedPresentation.of(visible: visible, graduated: before, expanded: record.expanded,
                                                     left: 1), .card, "first week: the whole card")
        XCTAssertEqual(HomeArrangement.of(setupVisible: visible, graduated: before), .firstWeek)

        let after = HomeSetup.hasChatsInMemory([row("chat-export:claude", .harness, episodes: 30, entities: 9)]) == true
        XCTAssertTrue(after, "Sleep wrote pages from the import")
        let rows = [gsRow("agent:codex", .on), gsRow("browser:safari-bookmarks", .needsAction("Allow"))]
        XCTAssertEqual(GettingStartedPresentation.of(visible: visible, graduated: after, expanded: record.expanded,
                                                     left: HomeSetup.thingsLeft(rows)), .line(left: 1))
        XCTAssertEqual(HomeArrangement.of(setupVisible: visible, graduated: after), .returning)
        let done = [gsRow("agent:codex", .on), gsRow("browser:safari-bookmarks", .on)]
        XCTAssertEqual(GettingStartedPresentation.of(visible: visible, graduated: after, expanded: record.expanded,
                                                     left: HomeSetup.thingsLeft(done)), .none)
    }

    // MARK: Words (review #6, #11)

    func testHomeSaysPlainWords() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(Copy.homeSetupLine(left: 1, locale: us), "Setup · 1 thing left")
        XCTAssertEqual(Copy.homeSetupLine(left: 2, locale: us), "Setup · 2 things left")
        XCTAssertEqual(Copy.homeWaitLine("Claude", requested: "2 hours ago"),
                       "Check your email for the Claude link · requested 2 hours ago")
        XCTAssertEqual(Copy.homeEmptyLabel(Copy.homeNeedsYou, note: Copy.homeNeedsYouNothing),
                       "Needs you · nothing right now")
        XCTAssertEqual(Copy.homeLastRead, "Last time Cicada read")
        XCTAssertEqual(Copy.gsScheduleQuestion, "Read new conversations automatically?")
        XCTAssertEqual(Copy.gsAfterImports, "After each import")
        XCTAssertEqual(Copy.gsAlsoFound, "Also on this Mac")
        XCTAssertTrue(Copy.foundRefused.hasPrefix("Reinstall Cicada"), "the fix leads")
        XCTAssertEqual(Copy.foundBackendDown, "Starting up…")
        XCTAssertFalse(WalkthroughVendor.claude.steps.joined().contains("Anthropic"), "the product the person knows")
        XCTAssertFalse(WalkthroughVendor.chatgpt.steps.joined().contains("OpenAI"))

        for text in Copy.homeFrontDoorLabels {
            XCTAssertLessThanOrEqual(text.count, 60, text)
        }
        for text in Copy.homeFrontDoorLabels + Copy.homeFrontDoorSentences {
            for word in ["episode", "claim", "token", "consolidat", "utc"] {
                XCTAssertFalse(text.lowercased().contains(word), "\(text) — \(word)")
            }
            XCTAssertFalse(text.contains("$"), text)
            XCTAssertFalse(text.contains("!"), text)
        }
    }
}
