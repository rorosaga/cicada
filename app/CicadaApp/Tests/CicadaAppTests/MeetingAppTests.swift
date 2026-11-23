import XCTest
@testable import CicadaApp

/// Owner 2026-11-23: a meeting's call app is its mark, not its name.
final class MeetingAppTests: XCTestCase {
    func testTheRecordersAppNamesFindTheirMarks() {
        XCTAssertEqual(MeetingApp.origin(for: "Google Meet"), "google-meet")
        XCTAssertEqual(MeetingApp.origin(for: "zoom.us"), "zoom")
        XCTAssertEqual(MeetingApp.origin(for: "Microsoft Teams"), "microsoft-teams")
        XCTAssertEqual(MeetingApp.origin(for: "Slack"), "slack")
        XCTAssertEqual(MeetingApp.origin(for: "Discord"), "discord")
        XCTAssertEqual(MeetingApp.origin(for: "FaceTime"), "facetime")
        XCTAssertNil(MeetingApp.origin(for: "Some Other App"))
        XCTAssertNil(MeetingApp.origin(for: nil))
    }

    func testEveryBundledCallAppMarkIsOnDisk() {
        for id in ["google-meet", "zoom", "microsoft-teams", "slack", "discord"] {
            let name = OriginIconography.logoName(for: id)
            XCTAssertNotNil(name, id)
            XCTAssertTrue(LogoImage.exists(name: name ?? ""), id)
        }
    }

    func testALengthReadsInMinutes() {
        XCTAssertEqual(MeetingApp.length(seconds: 1020), "17 min")
        XCTAssertEqual(MeetingApp.length(seconds: 20), "1 min")
        XCTAssertEqual(MeetingApp.length(seconds: 3900), "1 h 5 min")
        XCTAssertNil(MeetingApp.length(seconds: nil))
    }
}
