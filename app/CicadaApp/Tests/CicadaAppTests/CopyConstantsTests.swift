import XCTest
@testable import CicadaApp

/// G68 §2.8 — one voice, one place. A cross-page pointer names its
/// destination exactly as the sidebar/Settings spells it, and no view
/// re-types the literal.
final class CopyConstantsTests: XCTestCase {

    func testPointerNamesItsDestinationExactly() {
        XCTAssertEqual(Copy.settingsPlansAndKeys, "\(Copy.settings) → \(Copy.plansAndKeys)")
        XCTAssertTrue(Copy.noConnections.contains(Copy.settingsPlansAndKeys),
                      "the empty-connections line must point somewhere real")
        XCTAssertEqual(Copy.settingsPrivacy, "\(Copy.settings) → \(Copy.privacyAndData)")
    }

    /// The app is single-user; the observer is "You", never the account
    /// holder's first name.
    func testTheUserObserverIsCalledYou() {
        XCTAssertEqual(Copy.you, "You")
        XCTAssertEqual(Observer.rodrigo.label, Copy.you)
        XCTAssertEqual(Observer.agent.label, "Cicada")
    }

    /// Clusters counts entities and groups — it never claimed either was an
    /// "auto-detected cluster".
    func testClusterCountPluralisesBothNouns() {
        XCTAssertEqual(Copy.clusterCount(entities: 1, groups: 1), "1 entity in 1 group")
        XCTAssertEqual(Copy.clusterCount(entities: 412, groups: 9), "412 entities in 9 groups")
        XCTAssertEqual(Copy.clusterCount(entities: 0, groups: 0), "0 entities in 0 groups")
    }

    /// House rule: one sentence, at most 60 characters, and never a repeat of
    /// the page title it sits under.
    func testSubtitlesAreShortAndDoNotRepeatTheirTitle() {
        let pairs: [(title: String, subtitle: String)] = [
            ("Clusters", Copy.clustersSubtitle),
            ("Feed", Copy.feedSubtitle),
            ("Sleep", Copy.sleepSubtitle),
            ("Inbox", Copy.inboxSubtitle),
            (Copy.agents, Copy.agentsSubtitle),
            (Copy.plansAndKeys, Copy.plansAndKeysSubtitle),
            (Copy.sleepSettings, Copy.sleepSettingsSubtitle),
            (Copy.sources, Copy.sourcesSubtitle),
            (Copy.integrations, Copy.integrationsSubtitle),
            (Copy.general, Copy.generalSubtitle),
            (Copy.engines, Copy.enginesSubtitle),
            (Copy.fromAnywhere, Copy.remoteSubtitle),
            (Copy.youSection, Copy.youSubtitle),
            (Copy.privacyAndData, Copy.privacySubtitle),
            (Copy.memorySection, Copy.memorySubtitle),
            (Copy.advanced, Copy.advancedSubtitle),
            (Copy.skills, Copy.skillsSubtitle),
        ]
        for (title, subtitle) in pairs {
            XCTAssertLessThanOrEqual(subtitle.count, 60, "\(title): \"\(subtitle)\"")
            XCTAssertFalse(subtitle.lowercased().contains(title.lowercased()), "\(title) repeats itself")
            XCTAssertFalse(subtitle.lowercased().contains("page"), "\(title) says \"page\"")
        }
    }

    /// G71 §4.2 — every export platform gets a written step path, and it lives
    /// in Copy so no view retypes it.
    func testEveryExportStepPathIsRoutedThroughCopy() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertEqual(vendor.stepPath, Copy.exportStepPath(vendor))
            XCTAssertFalse(Copy.exportStepPath(vendor).isEmpty)
        }
    }

    /// Track P — the `?` popover is reachable from Graph, Clusters and Feed,
    /// so every sentence in it has to be true on all three. Two things it
    /// used to get wrong: capture was described as an MCP-client property
    /// (G105 replaced that with the harness's own Stop hook) and
    /// consolidation was described as automatic (a fresh install's schedule
    /// is `manual` — `api/services/sleep_scheduler.py::_DEFAULT`).
    func testTheAboutPopoverDoesNotClaimAutomaticConsolidationOrMCPCapture() {
        let sleep = Copy.aboutCicadaSleep
        XCTAssertFalse(sleep.lowercased().contains("automatically"))
        XCTAssertFalse(sleep.lowercased().contains("mcp client"))
        XCTAssertTrue(sleep.contains(Copy.settingsSleep), "it must point at the place a schedule is set")
        XCTAssertFalse(Copy.aboutCicadaCapture.lowercased().contains("mcp client"))
    }

    /// Track P R3/R4 — the label must name the schedule `ScheduleToggle.
    /// toggled(on: true, current: manual)` actually writes, or the toggle
    /// promises one thing and does another. `03:00` is
    /// `sleep_scheduler._DEFAULT`'s hour.
    func testTheOnboardingToggleLabelNamesTheScheduleItWrites() {
        XCTAssertTrue(Copy.onboardingRunNightly.contains("3:00"))
        XCTAssertEqual(ScheduleToggle.toggled(on: true,
                                              current: ScheduleConfig(mode: "manual", hour: 3, minute: 0)).hour, 3)
    }

    /// Track P — the empty state must say what to DO, not just that there is
    /// nothing (the same bar `emptyGraphMessage` set for G117).
    func testIntegrationsEmptyStateNamesTheThingToCheck() {
        XCTAssertFalse(Copy.integrationsEmpty.isEmpty)
        XCTAssertTrue(Copy.integrationsEmpty.lowercased().contains("backend"))
    }

    /// CI-style grep: these literals exist once, in Copy.swift. The whole file
    /// is scanned, comments included — a comment that repeats a label is
    /// exactly how these strings drifted in the first place. "on the Capture
    /// page" is banned rather than "the Capture page" so that the descriptive
    /// comments naming the *component*'s origin ("the Capture page's picker")
    /// survive; what must not come back is a POINTER to a page being retired.
    func testNoViewRetypesAPointerLiteral() throws {
        let banned = ["\"Plans & keys\"", "\"Rodrigo\"", "Setup › Connections", "on the Capture page"]
        for file in try ThemeTokenTests.swiftSources() {
            if file.lastPathComponent == "Copy.swift" { continue }
            let text = try String(contentsOf: file, encoding: .utf8)
            for literal in banned {
                XCTAssertFalse(text.contains(literal),
                               "\(file.lastPathComponent) re-types \(literal) — use Copy")
            }
        }
    }

    /// Track I T4 — the intake and found-row labels are short, and "claim" never
    /// reaches onboarding copy (design §7: the word means nothing to a new person).
    func testIntakeLabelsAreShortAndNeverSayClaim() {
        XCTAssertGreaterThan(Copy.intakeLabels.count, 20, "a lint over nothing passes vacuously")
        for label in Copy.intakeLabels {
            XCTAssertLessThanOrEqual(label.count, 60, label)
            XCTAssertFalse(label.lowercased().contains("claim"), label)
        }
        for sentence in Copy.intakeSentences {
            XCTAssertFalse(sentence.lowercased().contains("claim"), sentence)
        }
    }

    /// Track I final review, findings 6 and 7: a refusal never tells the person
    /// to run by hand what the allowlist refused, and the drop zone never
    /// promises "nothing is read" — the sniff reads the file, and "read" is a
    /// Sleep read a schedule runs unasked.
    func testIntakeCopyNeverUndoesARefusalOrPromisesNoRead() {
        XCTAssertFalse(Copy.foundRefused.localizedCaseInsensitiveContains("terminal"))
        XCTAssertFalse(Copy.foundRefused.localizedCaseInsensitiveContains("copy them"))
        XCTAssertFalse(Copy.intakeDropSubtitle.localizedCaseInsensitiveContains("read"))
    }
}
