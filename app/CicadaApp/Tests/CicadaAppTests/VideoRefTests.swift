import XCTest
@testable import CicadaApp

/// R-V8: the Swift half of the one classification table. This file and
/// `api/tests/test_video_urls.py` read the SAME
/// `api/tests/fixtures/video_urls.json` — add a provider on one side only and
/// the other side goes red. The `#filePath` walk (and its non-vacuous guard)
/// is the pattern `FontLiteralLintTests` already uses.
final class VideoRefTests: XCTestCase {
    private struct Case: Decodable {
        let url: String
        let provider: String?
        let kind: String?
        let videoId: String?
        let embedUrl: String?
        let why: String
    }
    private struct Fixture: Decodable { let cases: [Case] }

    private func fixture() throws -> [Case] {
        // …/Tests/CicadaAppTests/<this file> → …/CicadaApp → …/app → repo root
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/video_urls.json")
        let data = try Data(contentsOf: file)
        let cases = try JSONDecoder().decode(Fixture.self, from: data).cases
        XCTAssertGreaterThanOrEqual(
            cases.count, 40,
            "read \(cases.count) rows from \(file.path) — a table test over 0 rows passes vacuously")
        return cases
    }

    func testResolveMatchesTheSharedFixture() throws {
        for c in try fixture() {
            let ref = VideoRef.resolve(c.url)
            guard let provider = c.provider else {
                XCTAssertNil(ref, "\(c.url) should not classify (\(c.why))")
                continue
            }
            guard let ref else {
                // `continue`, never `return`: a `return XCTFail(...)` here
                // would abandon the remaining ~45 rows on the first failure
                // and report one drift instead of all of them.
                XCTFail("\(c.url) should classify (\(c.why))"); continue
            }
            XCTAssertEqual(ref.provider.rawValue, provider, c.url)
            XCTAssertEqual(ref.kind.rawValue, c.kind, c.url)
            XCTAssertEqual(ref.videoId, c.videoId, c.url)
            XCTAssertEqual(ref.embedURL?.absoluteString, c.embedUrl, c.url)
            XCTAssertEqual(ref.watchURL.absoluteString, c.url, c.url)
        }
    }

    func testResolveIsTotal() {
        for raw in ["", "   ", "not a url", "http://", "https://", "file://",
                    "javascript:alert(1)//a.mp4", "mailto:someone@example.com", "://broken",
                    "https://" + String(repeating: "a", count: 10_000) + ".com/clip.mp4"] {
            _ = VideoRef.resolve(raw)   // R2: must not trap
        }
    }

    func testOnlyEmbedKindsCarryAnEmbedURL() throws {
        for c in try fixture() where c.kind != "embed" {
            XCTAssertNil(VideoRef.resolve(c.url)?.embedURL, c.url)
        }
    }

    func testAutoplayIsAddedOnlyWhereTheProviderDocumentsIt() {
        // R11: YouTube and Vimeo only; TikTok/Loom get their plain player url.
        XCTAssertEqual(VideoRef.resolve("https://www.youtube.com/watch?v=vid00000001")?.autoplayURL?.absoluteString,
                       "https://www.youtube-nocookie.com/embed/vid00000001?autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.autoplayURL?.absoluteString,
                       "https://player.vimeo.com/video/123456789?autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789/abc123def4")?.autoplayURL?.absoluteString,
                       "https://player.vimeo.com/video/123456789?h=abc123def4&autoplay=1")
        XCTAssertEqual(VideoRef.resolve("https://www.loom.com/share/abc123def4567890abc123def4567890")?.autoplayURL?.absoluteString,
                       "https://www.loom.com/embed/abc123def4567890abc123def4567890")
        XCTAssertNil(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.autoplayURL)
    }

    func testIsPlayableExcludesExternal() {
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://example.com/media/clip.mp4")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.isPlayable, false)
        XCTAssertEqual(VideoRef.resolve("https://vm.tiktok.com/ZMexample/")?.isPlayable, false)
    }

    func testDurationLabel() {
        // R17: absent means absent — nothing is rendered, nothing is guessed.
        XCTAssertNil(VideoRef.durationLabel(nil))
        XCTAssertNil(VideoRef.durationLabel(0))
        XCTAssertNil(VideoRef.durationLabel(-5))
        XCTAssertEqual(VideoRef.durationLabel(9), "0:09")
        XCTAssertEqual(VideoRef.durationLabel(95), "1:35")
        XCTAssertEqual(VideoRef.durationLabel(3725), "1:02:05")
    }
}
