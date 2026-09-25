import XCTest
@testable import CicadaApp

/// R-V6: the seam, not a mock. Everything worth testing about playback is a
/// decision made BEFORE AVFoundation is involved — which controller to keep,
/// whether space was handled, whether a local file is even readable — so the
/// tests drive a fake and no AVPlayer is ever constructed. "Does this codec
/// decode?" is a stated manual check (plan R8), not a mocked green.
final class FakePlaybackController: VideoPlaybackController {
    let url: URL
    private(set) var isPlaying = false
    private(set) var toggles = 0
    init(url: URL) { self.url = url }
    func play() { isPlaying = true }
    func pause() { isPlaying = false }
    func toggle() { toggles += 1; isPlaying.toggle() }
}

final class VideoPlayerTests: XCTestCase {
    private let a = URL(string: "https://example.com/media/clip.mp4")!
    private let b = URL(string: "https://example.com/media/other.mp4")!

    func testARerenderWithTheSameURLKeepsTheSameController() {
        let first = VideoPlayerModel.controller(for: a, existing: nil, make: FakePlaybackController.init)
        let second = VideoPlayerModel.controller(for: a, existing: first, make: FakePlaybackController.init)
        // The bug this guards is the one WebView.updateNSView already guards:
        // a SwiftUI re-render must not restart playback.
        XCTAssertTrue(first === second)
    }

    func testChangingTheURLSwapsTheControllerAndStartsPaused() {
        let first = VideoPlayerModel.controller(for: a, existing: nil, make: FakePlaybackController.init)
        first.play()
        let second = VideoPlayerModel.controller(for: b, existing: first, make: FakePlaybackController.init)
        XCTAssertFalse(first === second)
        XCTAssertEqual(second.url, b)
        XCTAssertFalse(second.isPlaying)
    }

    func testSpaceTogglesExactlyOncePerPressAndReportsHandled() {
        let c = FakePlaybackController(url: a)
        XCTAssertTrue(VideoPlayerModel.handleSpace(c))
        XCTAssertEqual(c.toggles, 1)
        XCTAssertTrue(c.isPlaying)
        XCTAssertTrue(VideoPlayerModel.handleSpace(c))
        XCTAssertEqual(c.toggles, 2)
        XCTAssertFalse(c.isPlaying)
    }

    func testSpaceWithNoControllerIsNotHandled() {
        // R10: the key must fall through rather than be swallowed when there
        // is nothing to toggle.
        XCTAssertFalse(VideoPlayerModel.handleSpace(nil))
    }

    func testARemoteURLIsAlwaysPlayable() {
        XCTAssertEqual(VideoPlayerModel.state(for: a), .playable(a))
    }

    func testAMissingLocalFileIsUnreadableAndNamesItsPath() throws {
        let missing = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cicada-video-\(UUID().uuidString)/clip.mov")
        XCTAssertEqual(VideoPlayerModel.state(for: missing), .unreadable(path: missing.path))
    }

    func testAReadableLocalFileIsPlayable() throws {
        let file = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cicada-video-\(UUID().uuidString).mov")
        try Data("not really a movie".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        // R9 is a READABILITY gate, not a decode gate — whether AVFoundation
        // can decode the bytes is the manual check, and a black rectangle is
        // never the answer either way.
        XCTAssertEqual(VideoPlayerModel.state(for: file), .playable(file))
    }
}
