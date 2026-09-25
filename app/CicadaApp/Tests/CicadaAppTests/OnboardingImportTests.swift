import XCTest
@testable import CicadaApp

/// R-OB6 … R-OB9 and the owner's decision 2 — only connections known to work, Browsers first, no Obsidian, no social
/// media, and a table the Contacts and tab-group rows join as one entry each.
@MainActor
final class OnboardingImportTests: XCTestCase {
    private func inventory(_ ids: [String]) -> BrowserInventory {
        BrowserInventory(installed: BrowserInventory.catalog.filter { ids.contains($0.id) })
    }

    func testOnlySupportedInstalledBrowsersGetARowAndTheyComeFirst() {
        let entries = ImportCatalog.entries(ImportContext(browsers: inventory(["safari", "chrome", "arc"])))
        XCTAssertEqual(entries.filter { $0.parent == nil }.prefix(2).map(\.id),
                       [.browser("chrome-bookmarks"), .browser("safari-bookmarks")], "Chrome's sub-row aside")
        XCTAssertFalse(entries.contains { $0.title == "Arc" }, "an unsupported browser is named once, never a row")
        XCTAssertEqual(entries.first { $0.id == .browser("safari-bookmarks") }?.meta,
                       BrowserInventory.readsLine(BrowserInventory.spec(id: "safari")!),
                       "Safari names all four things it reads")
    }

    func testTheOtherCategoriesAndNothingUntested() {
        let entries = ImportCatalog.entries(ImportContext(browsers: inventory(["safari"]), wisprInstalled: true))
        XCTAssertEqual(entries.map(\.category),
                       [.browsers, .calendarAndContacts, .calendarAndContacts, .notesAndFiles, .voiceAndMeetings])
        let words = entries.map { "\($0.title) \($0.meta ?? "")".lowercased() }.joined(separator: " ")
        for banned in ["obsidian", "pinterest", "reddit", "instagram", "tiktok", "linkedin", "youtube", " x "] {
            XCTAssertFalse(words.contains(banned), banned)
        }
        XCTAssertFalse(ImportCatalog.entries(ImportContext(browsers: inventory(["safari"])))
                        .contains { $0.category == .voiceAndMeetings }, "Wispr Flow only once it is on this Mac")
    }

    /// R-OB11 — Apple Notes reads once and is never promised to keep up.
    func testAppleNotesIsAOneTimeReadAndSaysSo() throws {
        let notes = try XCTUnwrap(ImportCatalog.entries(ImportContext()).first { $0.id == .app("notes") })
        XCTAssertFalse(notes.keepsUp)
        XCTAssertFalse((notes.idleLine ?? "").lowercased().contains("keeps up"))
    }

    /// Seam 4 — a child joins as one entry and sits right under its parent; the label follows the rows.
    func testASubRowSitsUnderItsParentAndACategoryNeverPromisesARow() {
        let chrome = ImportEntry(id: .browser("chrome-bookmarks"), category: .browsers, title: "Chrome", origin: "chrome-bookmark")
        let safari = ImportEntry(id: .browser("safari-bookmarks"), category: .browsers, title: "Safari", origin: "safari-bookmark")
        let groups = ImportEntry(id: .app("chrome-tab-groups"), category: .browsers, title: "Open tab groups",
                                 origin: "chrome-bookmark", parent: .browser("chrome-bookmarks"))
        XCTAssertEqual(ImportCatalog.ordered([chrome, safari, groups]).map(\.id),
                       [chrome.id, groups.id, safari.id])
        let calendar = ImportEntry(id: .app("calendar-local"), category: .calendarAndContacts, title: "Calendar",
                                   origin: "calendar-local")
        XCTAssertEqual(ImportCategory.calendarAndContacts.title(entries: [calendar]), "Calendar")
        let contacts = ImportEntry(id: .app("contacts-local"), category: .calendarAndContacts, title: "Contacts",
                                   origin: "contacts-local")
        XCTAssertEqual(ImportCategory.calendarAndContacts.title(entries: [calendar, contacts]), "Calendar & contacts")
    }

    /// Seam 4 (G154) — Contacts is one entry beside Calendar, and the category's label follows it by itself.
    func testContactsJoinsCalendarAndTheCategoryReadsCalendarAndContacts() throws {
        let entries = ImportCatalog.entries(ImportContext())
        let group = try XCTUnwrap(ImportCatalog.grouped(entries).first { $0.category == .calendarAndContacts })
        XCTAssertEqual(group.entries.map(\.id), [.app(AppSourceDrivers.calendar), .app(AppSourceDrivers.contacts)])
        let contacts = group.entries[1]
        XCTAssertEqual(contacts.origin, "contacts-local", "the installed Contacts app's own mark (DR-52)")
        XCTAssertTrue(contacts.keepsUp)
        XCTAssertEqual(ImportCategory.calendarAndContacts.title(entries: entries), Copy.importCalendarAndContacts)
        XCTAssertEqual(ImportCategory.calendarAndContacts.title(entries: [group.entries[0]]), Copy.importCalendar)
    }

    /// Seam 4 (G160) — Chrome's open tab groups are their own tick, right under Chrome, and only where Chrome is.
    func testTheTabGroupSubRowSitsRightAfterChromeOnlyWhenChromeIsSupported() throws {
        let entries = ImportCatalog.entries(ImportContext(browsers: inventory(["safari", "chrome", "brave"])))
        XCTAssertEqual(entries.prefix(4).map(\.id), [.browser("chrome-bookmarks"), .app(AppSourceDrivers.tabGroups),
                                                     .browser("safari-bookmarks"), .browser("brave-bookmarks")])
        let groups = entries[1]
        XCTAssertEqual(groups.parent, .browser("chrome-bookmarks"))
        XCTAssertEqual(groups.category, .browsers)
        XCTAssertEqual(groups.origin, "chrome-tab-group", "Chrome's own mark")
        for ids in [["safari", "brave"], []] {
            XCTAssertFalse(ImportCatalog.entries(ImportContext(browsers: inventory(ids)))
                            .contains { $0.id == .app(AppSourceDrivers.tabGroups) }, "no Chrome, no sub-row: \(ids)")
        }
    }

    /// A child with no parent row is never drawn on its own.
    func testASubRowWithoutItsParentIsDropped() {
        let safari = ImportEntry(id: .browser("safari-bookmarks"), category: .browsers, title: "Safari", origin: "safari-bookmark")
        let groups = ImportEntry(id: .app("chrome-tab-groups"), category: .browsers, title: "Open tab groups",
                                 origin: "chrome-tab-group", parent: .browser("chrome-bookmarks"))
        XCTAssertEqual(ImportCatalog.ordered([safari, groups]).map(\.id), [safari.id])
    }

    /// Seam-4 final review — the driver keeps the person's own dictation setting, so the meta says what is true.
    func testWisprFlowsMetaFollowsTheDictationSetting() {
        func meta(_ dictation: Bool) -> String? {
            ImportCatalog.entries(ImportContext(wisprInstalled: true, wisprDictation: dictation))
                .first { $0.id == .app(AppSourceDrivers.wispr) }?.meta
        }
        XCTAssertEqual(meta(false), Copy.importWisprMeta)
        XCTAssertEqual(meta(true), Copy.importWisprMetaDictation)
        XCTAssertFalse(Copy.importWisprMeta.lowercased().contains("dictation"), "never promises dictation stays off")
    }

    /// R-OB6 / R-OB8 — nothing is pre-ticked; a started row reads ticked; a one-time read becomes a ✓.
    func testTheControlFollowsTheRowAndNeverTicksForThePerson() {
        let entry = ImportEntry(id: .app("notes"), category: .notesAndFiles, title: "Apple Notes", origin: "apple-notes",
                                keepsUp: false)
        XCTAssertEqual(ImportRows.control(entry, phase: nil), .tick(on: false))
        XCTAssertEqual(ImportRows.control(entry, phase: .comingIn), .locked, "a one-time read finishes on its own")
        XCTAssertEqual(ImportRows.control(entry, phase: .done), .done)
        let browser = ImportEntry(id: .browser("chrome-bookmarks"), category: .browsers, title: "Chrome", origin: "chrome-bookmark")
        XCTAssertEqual(ImportRows.control(browser, phase: .comingIn), .tick(on: true), "untick stops it (R-OB8)")
        XCTAssertEqual(ImportRows.control(browser, phase: .done), .tick(on: true))
        XCTAssertEqual(ImportRows.control(browser, phase: .off), .tick(on: false))
        // A row waiting on the person — a blocked Safari before anyone ticked it (`LocalInventory` probes Full Disk
        // Access up front, so its derived state is `.needsAction(Allow…)`), or a failure — is never drawn ticked:
        // drawn ticked, its first click would be an untick and the row could never start. Its tick is the retry.
        XCTAssertEqual(ImportRows.control(browser, phase: .needsYou), .tick(on: false), "R-OB6, R-OB7")
    }

    /// R-OB7 (W5 kept) — the Allow… click was the tick: the grant starts that row, once.
    func testAGrantStartsTheRowWhoseAllowWasClicked() {
        let safari = FoundItem(id: .browser("safari-bookmarks"), group: .browsers, title: "Safari", isPresent: true,
                               content: .ownIntentionalAct, readiness: .ready, opensAnotherApp: false)
        XCTAssertEqual(ImportTicks.startsAfterGrant(items: [safari], allowRequested: [safari.id], started: []),
                       [safari.id])
        XCTAssertEqual(ImportTicks.startsAfterGrant(items: [safari], allowRequested: [safari.id], started: [safari.id]), [])
        XCTAssertEqual(ImportTicks.startsAfterGrant(items: [safari], allowRequested: [], started: []), [],
                       "no Allow… click, no start (R-OB6)")
    }
}
