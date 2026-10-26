import XCTest
@testable import CicadaApp

/// Report a problem (tester readiness, 2026-10-26): what the app adds on top of the backend's redacted report, and the
/// one destination Send opens. The backend's redaction is `api/tests/test_diagnostics.py`'s.
final class ProblemReportTests: XCTestCase {
    func testTheHeaderNamesTheAppBuildAndMacOSAndNoOne() {
        let header = ProblemReport.header(app: AppVersion(short: "0.8.0", build: "142"), macOS: "15.1.0")
        XCTAssertTrue(header.hasPrefix("Cicada problem report\nApp: 0.8.0 (build 142)\nmacOS: 15.1.0\n"))
        XCTAssertTrue(header.contains("Known issue: after an update, macOS may ask again for permissions"))
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

    /// Owner 2026-10-26: Send is a private email whose address only a release build carries (Info.plist, from CI's
    /// `CICADA_REPORT_EMAIL`); with none there is no Send, and never a public page.
    func testSendIsAPrivateEmailOnlyWhenTheReleaseCarriesTheAddress() throws {
        XCTAssertNil(ProblemReport.reportEmail(info: [:]), "a developer build carries none")
        XCTAssertNil(ProblemReport.reportEmail(info: [ProblemReport.infoKey: "  "]))
        XCTAssertNil(ProblemReport.reportEmail(info: [ProblemReport.infoKey: "not an address"]))
        XCTAssertNil(ProblemReport.reportEmail(info: [ProblemReport.infoKey: "a@b.example?cc=x@y.example"]))
        XCTAssertEqual(ProblemReport.reportEmail(info: [ProblemReport.infoKey: " reports@example.com "]),
                       "reports@example.com")
        XCTAssertNil(ProblemReport.reportEmail(), "the test bundle carries no address: the repo holds none")
        XCTAssertNil(ProblemReport.sendURL(email: nil))
        let url = try XCTUnwrap(ProblemReport.sendURL(email: "reports@example.com"))
        XCTAssertEqual(url.scheme, "mailto")
        XCTAssertTrue(url.absoluteString.hasPrefix("mailto:reports@example.com?subject="))
        let items = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        let body = try XCTUnwrap(items.first { $0.name == "body" }?.value)
        XCTAssertFalse(body.contains("Backend:"), "the report itself is pasted by the person, never put in the link")
        XCTAssertFalse(url.absoluteString.contains("github"), "never a public page")
        XCTAssertTrue(Copy.ReportProblem.noSendNote.contains("the person who gave you Cicada"))
    }

    func testNoReportAddressIsCommittedToTheRepo() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../")
        let bundle = try String(contentsOf: root.appendingPathComponent("bundle.sh"), encoding: .utf8)
        XCTAssertTrue(bundle.contains("plutil -replace CicadaReportEmail -string \"$CICADA_REPORT_EMAIL\""))
        XCTAssertNil(bundle.range(of: #"CICADA_REPORT_EMAIL:-[^}]"#, options: .regularExpression),
                     "no default address in the repo")
        XCTAssertNil(bundle.range(of: #"CicadaReportEmail -string "[^$]"#, options: .regularExpression))
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
