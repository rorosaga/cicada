import XCTest
@testable import CicadaApp

/// Report a problem (tester readiness, 2026-10-26): what the app adds on top of the backend's redacted report, and the
/// one destination Send opens. The backend's redaction is `api/tests/test_diagnostics.py`'s.
final class ProblemReportTests: XCTestCase {
    func testTheHeaderNamesTheAppBuildAndMacOSAndNoOne() {
        let header = ProblemReport.header(app: AppVersion(short: "0.8.0", build: "142"), macOS: "15.1.0")
        XCTAssertEqual(header, "Cicada problem report\nApp: 0.8.0 (build 142)\nmacOS: 15.1.0")
        XCTAssertTrue(ProblemReport.header(app: AppVersion(short: nil, build: nil), macOS: "15.1.0")
            .contains("App: development build"))
        XCTAssertFalse(header.contains(NSUserName()), "never the account's name")
        XCTAssertFalse(header.contains(NSHomeDirectory()), "never the home path")
    }

    func testTheReportIsTheHeaderThenTheBackendsHalfOrSaysItDidNotAnswer() {
        XCTAssertEqual(ProblemReport.compose(header: "H", backend: "Backend: 1\n"), "H\nBackend: 1\n")
        XCTAssertEqual(ProblemReport.compose(header: "H", backend: nil), "H\n\(Copy.ReportProblem.backendUnreachable)\n")
        XCTAssertEqual(ProblemReport.compose(header: "H", backend: "  "), "H\n\(Copy.ReportProblem.backendUnreachable)\n")
    }

    /// One constant decides where Send goes: for now the repository's public new-issue page, said as public.
    func testSendOpensTheOneDestinationWithTheShortTemplate() throws {
        XCTAssertEqual(ProblemReport.destination.absoluteString, "https://github.com/rorosaga/cicada/issues/new")
        XCTAssertTrue(ProblemReport.destinationIsPublic)
        let url = ProblemReport.sendURL()
        let items = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(items.first { $0.name == "title" }?.value, ProblemReport.issueTitle)
        let body = try XCTUnwrap(items.first { $0.name == "body" }?.value)
        XCTAssertTrue(body.contains("This issue is public"))
        XCTAssertFalse(body.contains("Backend:"), "the report itself is pasted by the person, never put in the URL")
        let mail = ProblemReport.sendURL(destination: URL(string: "mailto:reports@example.com")!)
        XCTAssertTrue(mail.absoluteString.hasPrefix("mailto:reports@example.com?subject="))
        XCTAssertTrue(Copy.ReportProblem.publicNote.contains("public"))
    }

    func testTheSavedFileNameIsDatedAndNamesNoOne() {
        let day = ISODate.parse("2026-10-26T10:05:00Z")!
        XCTAssertTrue(ProblemReport.fileName(now: day).hasPrefix("cicada-report-2026-10-2"))
        XCTAssertTrue(ProblemReport.fileName(now: day).hasSuffix(".txt"))
    }

    func testTheSheetsLabelsAreShortAndSettingsListsTheRow() {
        for label in Copy.ReportProblem.labels { XCTAssertLessThanOrEqual(label.count, 60, label) }
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.reportProblem))
    }
}
