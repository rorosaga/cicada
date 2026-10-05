import XCTest
@testable import CicadaApp

/// Track Z, Z3 — the page's second surface (R-Z6, spec decision 16) and the
/// strip's news-only rule.
final class SleepDetailsTests: XCTestCase {

    /// Decision 16: closed by default, remembered per viewer.
    func test_detailsIsClosedByDefaultAndRememberedUnderOneKey() {
        XCTAssertEqual(SleepDetails.openKey, "cicada.sleep.detailsOpen")
        XCTAssertFalse(SleepDetails.defaultOpen)
    }

    /// Last cycle appears only when there is something to say about it.
    func test_lastCycleShowsOnlyWithNews() {
        XCTAssertFalse(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: "boom", cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: true, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: true, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: "w"))
    }

    /// R-Z6 — the strip is the running instrument and the frozen record of a
    /// cancel or failure (P15); an idle, successful page has nothing for it to say.
    func test_theStripShowsOnlyWhileRunningOrFrozen() {
        XCTAssertFalse(stageStripIsVisible(isRunning: false, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: true, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: true, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: false, failed: true))
    }

    func test_everySectionHasItsOwnAnchor() {
        let ids = DetailsSection.allCases.map(\.anchorID)
        XCTAssertEqual(ids, ["details.lastCycle", "details.waiting", "details.readout", "details.pastNights"])
        XCTAssertEqual(Set(ids).count, ids.count)
    }

    /// What left the page stays gone: the second column, the duplicate worm
    /// at the strip's end, and the Memory sources card (Sources v2 draws the
    /// same projection).
    func test_whatLeftThePageStaysGone() throws {
        var text = ""
        for file in try SleepNumbersLintTests.sleepSources() {
            text += try String(contentsOf: file, encoding: .utf8)
        }
        XCTAssertFalse(text.contains("MemorySourcesCard("))
        XCTAssertFalse(text.contains("sleepLayout(width:"))
        XCTAssertFalse(text.contains("caughtUpWorm"))
        XCTAssertFalse(try SleepNumbersLintTests.sleepSources().contains { $0.lastPathComponent == "MemorySourcesCard.swift" })
    }

    /// R-HS15 — Last cycle's four banners are rows in words, in the order the page always told them;
    /// a failure and a warning need the person (the `warning` glyph), a cancel and a cap do not.
    func test_lastCycleRowsSayWhatHappenedInWords() throws {
        let status = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(Self.cappedStatusJSON.utf8))
        let rows = LastCycleRow.rows(pageError: "The local backend didn't answer.", cancelled: true, capped: true,
                                     indexWarning: "The vector index wasn't rebuilt.", status: status,
                                     locale: Locale(identifier: "en_US"))
        XCTAssertEqual(rows.map(\.kind), [.failed, .cancelled, .capped, .warning])
        XCTAssertEqual(rows.map(\.title), ["Sleep cycle error", "Cancelled", "Episode cap reached (2)",
                                           "Completed with warnings"])
        XCTAssertEqual(rows[1].text, "Stopped cleanly before any writes — nothing was lost.")
        XCTAssertEqual(rows[2].text, "2 of 3 processed — the rest stay queued for the next cycle.")
        XCTAssertEqual(rows.map(\.needsYou), [true, false, false, true])
    }

    func test_lastCycleRowsAppearExactlyWhenTheSectionDoes() throws {
        let status = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(Self.cappedStatusJSON.utf8))
        for error in [nil, "boom"] as [String?] {
            for cancelled in [false, true] {
                for capped in [false, true] {
                    for warning in [nil, "", "w"] as [String?] {
                        let rows = LastCycleRow.rows(pageError: error, cancelled: cancelled, capped: capped,
                                                     indexWarning: warning, status: status)
                        XCTAssertEqual(!rows.isEmpty, lastCycleSectionIsVisible(pageError: error, cancelled: cancelled,
                                                                                capped: capped, indexWarning: warning))
                    }
                }
            }
        }
    }

    /// DR-37, DR-7 — Details carries no card and no tinted fill: labels over rows.
    func test_detailsIsRowsNotCards() throws {
        for name in ["SleepDetails.swift", "StudyListCard.swift", "ConsolidationHistoryCard.swift", "EpisodeRow.swift"] {
            let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == name })
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains(".glassCard("), "\(name) — no card (DR-37)")
            for tint in ["danger.opacity(", "accent.opacity(", "warning.opacity(", "surfaceHover.opacity("] {
                XCTAssertFalse(text.contains(tint), "\(name) — \(tint) (DR-7)")
            }
        }
        let hero = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "SleepHero.swift" })
        let heroText = try String(contentsOf: hero, encoding: .utf8)
        XCTAssertEqual(heroText.components(separatedBy: ".glassCard(").count - 1, 0,
                       "the readout left its card too")
    }

    /// DR-48, DR-54 — an episode row's meta line: its time, and "read" once Sleep read it.
    func test_episodeRowMetaIsTheTimeAndWhetherItWasRead() {
        XCTAssertEqual(EpisodeRowText.time(""), "—")
        XCTAssertEqual(EpisodeRowText.time("not a date at all, longer than sixteen"), "not a date at al",
                       "the raw start (16 characters), never a blank")
        XCTAssertTrue(EpisodeRowText.meta(target: "example.com", processed: true).hasSuffix(" · read"))
        XCTAssertFalse(EpisodeRowText.meta(target: "example.com", processed: false).contains("read"))
    }

    /// Owner 2026-10-05 — a queued row names what a click copies, ends with its day, and its toast says what it copied.
    func test_episodeRowNamesWhatAClickCopiesAndEndsWithItsDay() {
        XCTAssertEqual(EpisodeRowText.target(kind: "link", value: "https://example.com/a/b?q=1", id: "ep_1"), "example.com/a/b")
        XCTAssertEqual(EpisodeRowText.target(kind: "link", value: "https://example.com/", id: "ep_1"), "example.com")
        XCTAssertEqual(EpisodeRowText.target(kind: "conversation", value: "0f3c1a2b-9d", id: "ep_1"), "Conversation 0f3c1a2b")
        XCTAssertEqual(EpisodeRowText.target(kind: "links", value: "https://a.example\nhttps://b.example", id: "ep_1"), "2 tab links")
        XCTAssertEqual(EpisodeRowText.target(kind: "path", value: "/tmp/notes/plans/q4.md", id: "ep_1"), "q4.md")
        XCTAssertEqual(EpisodeRowText.target(kind: nil, value: nil, id: "ep_1"), "ep_1", "an older backend copies the id")

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = ISO8601DateFormatter().date(from: "2026-10-05T12:00:00Z")!
        XCTAssertFalse(EpisodeRowText.day("2026-10-03T10:00:00Z", now: now, calendar: calendar).contains("2026"),
                       "this year's day carries no year")
        XCTAssertTrue(EpisodeRowText.day("2025-12-30T10:00:00Z", now: now, calendar: calendar).contains("2025"))
        XCTAssertEqual(EpisodeRowText.day("", now: now), "", "no raw stamp at the row's edge")

        XCTAssertEqual(Copy.SleepDetailsWords.copied("conversation"), "Conversation ID copied")
        XCTAssertEqual(Copy.SleepDetailsWords.copied("link"), "Link copied")
        XCTAssertEqual(Copy.SleepDetailsWords.copied(nil), "Episode ID copied")
        let help = EpisodeRowText.help(kind: "conversation", timestamp: "2026-10-01T09:00:00Z", changedAt: "2026-10-03T12:00:00Z")
        XCTAssertTrue(help.hasPrefix("Click to copy the conversation ID") && help.contains("Added") && help.contains("Updated"))
        XCTAssertFalse(EpisodeRowText.help(kind: "link", timestamp: "2026-10-01T09:00:00Z", changedAt: "2026-10-01T09:00:00Z")
            .contains("Updated"), "a row that never changed says when it arrived, once")
    }

    /// The queue item decodes what a click copies, and an older backend that sends none still decodes.
    func test_queueItemDecodesItsCopyTargetAndDay() throws {
        let new = try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id": "ep_1", "timestamp": "2026-10-01T09:00:00Z", "source": "codex", "origin": "codex", "preview": "",
         "chars": 3, "processed": false, "copyKind": "conversation", "copyValue": "sess-42", "changedAt": "2026-10-03T12:00:00Z"}
        """.utf8))
        XCTAssertEqual(new.copyKind, "conversation")
        XCTAssertEqual(new.copyValue, "sess-42")
        XCTAssertEqual(new.changedAt, "2026-10-03T12:00:00Z")
        let old = try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id": "ep_2", "timestamp": "2026-10-01T09:00:00Z", "source": "url", "preview": "", "processed": false}
        """.utf8))
        XCTAssertNil(old.copyValue)
        XCTAssertEqual(OriginIconography.label(for: "url"), "Link", "never \"Url\"")
    }

    /// A copy confirmation is brief; every other toast keeps the standard dwell, and each one restarts the timer.
    @MainActor
    func test_aCopyConfirmationIsBriefAndEveryToastRestartsItsTimer() {
        let store = Store()
        let before = store.toastSerial
        store.flash("Link copied")
        XCTAssertEqual(store.toastDwell, CicadaTiming.copiedConfirmation)
        store.toast = "Could not load the queue"
        XCTAssertEqual(store.toastDwell, CicadaTiming.toastDwell)
        store.flash("Link copied"); store.flash("Link copied")
        XCTAssertEqual(store.toastSerial, before + 4, "the same words twice still restart the timer")
    }

    private static let cappedStatusJSON = """
    {"status": "idle", "stage": 5, "episodesTotal": 2, "episodesQueued": 3, "episodeCap": 2, "cancelled": false}
    """
}
