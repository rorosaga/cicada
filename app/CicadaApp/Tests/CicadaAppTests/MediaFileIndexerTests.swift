import CoreGraphics
import ImageIO
import XCTest
@testable import CicadaApp

/// Meaning index 2 — a recording or video the person adds: read on this Mac, only derivatives posted, Speech
/// Recognition asked for only by the person's own drop. Fixtures only: no recogniser runs, no prompt is raised.
final class FakeSpeech: SpeechAuthorizing, @unchecked Sendable {
    var current: SpeechAccess
    var answer: SpeechAccess
    var requests = 0
    init(_ current: SpeechAccess, answer: SpeechAccess = .authorized) { self.current = current; self.answer = answer }
    func status() -> SpeechAccess { current }
    func request() async -> SpeechAccess { requests += 1; current = answer; return answer }
}

final class FakeTranscriber: Transcribing, @unchecked Sendable {
    var calls = 0
    var outcome: TranscribeOutcome = .words([TranscriptSegment(start: 0, end: 4, text: "Hello there."),
                                             TranscriptSegment(start: 4, end: 9, text: "The budget is due.")])
    func transcribe(_ url: URL, locale: Locale) async -> TranscribeOutcome { calls += 1; return outcome }
}

final class FakeSampler: FrameSampling, @unchecked Sendable {
    var calls = 0
    func frames(_ url: URL) async -> (length: Double?, frames: [KeptFrame]) {
        calls += 1
        return (120, [KeptFrame(t: 0, jpeg: Data([0xFF, 0xD8])), KeptFrame(t: 9, jpeg: Data([0xFF, 0xD8]))])
    }
}

final class FakeMediaAPI: MediaFilesAPI, @unchecked Sendable {
    var bodies: [[String: Any]] = []
    var frames: [Int] = []
    func postMediaFile(_ body: [String: Any]) async throws -> String { bodies.append(body); return "0123456789abcdef" }
    func postMediaFrames(fileId: String, frames: [KeptFrame]) async throws { self.frames.append(frames.count) }
}

@MainActor
final class MediaFileIndexerTests: XCTestCase {
    private var dir: URL!

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("media-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir) }

    private func file(_ name: String) throws -> URL {
        let url = dir.appendingPathComponent(name)
        try Data("not really a recording".utf8).write(to: url)
        return url
    }

    func testOnlyAudioAndVideoFilesAreMedia() throws {
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/memo.m4a")), .audio)
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/podcast.mp3")), .audio)
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/talk.mov")), .video)
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/clip.mp4")), .video)
        XCTAssertNil(MediaKind.of(URL(fileURLWithPath: "/x/conversations.json")))
        XCTAssertNil(MediaKind.of(URL(fileURLWithPath: "/x/notes.pdf")))
        XCTAssertTrue(MediaFileIndexer.media(in: [dir]).isEmpty, "a folder is never walked here")
    }

    func testSamplingIsEveryThreeSecondsCappedAtTwelveHundred() {
        XCTAssertEqual(MediaFrames.times(seconds: 10), [0, 3, 6, 9])
        XCTAssertEqual(MediaFrames.times(seconds: 3600).count, 1200)
        XCTAssertEqual(MediaFrames.times(seconds: 36000).count, 1200)
        XCTAssertEqual(MediaFrames.times(seconds: .nan), [0])
    }

    func testOneFrameIsKeptPerShot() {
        let a: UInt64 = 0, nearA: UInt64 = 0b1111, b: UInt64 = 0xFF00
        XCTAssertEqual(MediaFrames.keep([a, nearA, a, b, b, a]), [0, 3, 5],
                       "four bits or fewer from the last kept is the same shot")
    }

    private func picture(_ draw: (CGContext) -> Void, width: Int = 1280, height: Int = 720) -> CGImage {
        let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        draw(ctx)
        return ctx.makeImage()!
    }

    func testTheHashSeesAShotChangeAndTheFrameIsSmall() throws {
        let left = picture { $0.setFillColor(gray: 1, alpha: 1); $0.fill(CGRect(x: 0, y: 0, width: 640, height: 720)) }
        let top = picture { $0.setFillColor(gray: 1, alpha: 1); $0.fill(CGRect(x: 0, y: 360, width: 1280, height: 360)) }
        XCTAssertGreaterThan(MediaFrames.distance(MediaFrames.averageHash(left), MediaFrames.averageHash(top)),
                             MediaFrames.minBits)
        XCTAssertEqual(MediaFrames.distance(MediaFrames.averageHash(left), MediaFrames.averageHash(left)), 0)
        let jpeg = try XCTUnwrap(MediaFrames.jpeg(left))
        XCTAssertLessThanOrEqual(jpeg.count, 200 * 1024)
        let src = try XCTUnwrap(CGImageSourceCreateWithData(jpeg as CFData, nil))
        let img = try XCTUnwrap(CGImageSourceCreateImageAtIndex(src, 0, nil))
        XCTAssertLessThanOrEqual(img.width, 640)
        XCTAssertLessThanOrEqual(img.height, 400)
    }

    func testOnlyTheDerivativesArePostedNeverThePathOrTheBytes() async throws {
        let api = FakeMediaAPI(), sampler = FakeSampler()
        let ix = MediaFileIndexer(api: api, speech: FakeSpeech(.authorized), transcriber: FakeTranscriber(),
                                  sampler: sampler, locale: Locale(identifier: "en-US"))
        let out = await ix.add([try file("team sync.mov")])
        XCTAssertEqual(out, [.added(words: 2, frames: 2)])
        let body = try XCTUnwrap(api.bodies.first)
        XCTAssertEqual(body["name"] as? String, "team sync.mov")
        XCTAssertEqual(body["kind"] as? String, "video")
        XCTAssertEqual((body["sha256"] as? String)?.count, 64)
        XCTAssertEqual((body["segments"] as? [[String: Any]])?.count, 2)
        let text = "\(body)"
        XCTAssertFalse(text.contains(dir.path), "the file's path never leaves the app")
        XCTAssertFalse(text.contains("not really a recording"), "nor its bytes")
        XCTAssertEqual(api.frames, [2])
    }

    func testSpeechIsAskedForOnlyByThePersonsOwnDrop() async throws {
        let speech = FakeSpeech(.notDetermined)
        let ix = MediaFileIndexer(api: FakeMediaAPI(), speech: speech, transcriber: FakeTranscriber(),
                                  sampler: FakeSampler())
        let router = IntakeRouter(api: FakeIntakeAPI())
        _ = router
        XCTAssertEqual(speech.requests, 0, "creating the reader or the router never asks")
        _ = await ix.add([try file("notes.pdf")])
        XCTAssertEqual(speech.requests, 0, "nothing to transcribe, nothing asked")
        _ = await ix.add([try file("memo.m4a")])
        XCTAssertEqual(speech.requests, 1, "the drop of a recording asks once")
        _ = await ix.add([try file("memo2.m4a")])
        XCTAssertEqual(speech.requests, 1, "once answered, never asked again")
    }

    func testADenialKeepsTheFileWithoutItsWordsAndSaysSo() async throws {
        let transcriber = FakeTranscriber(), api = FakeMediaAPI()
        var said: [String] = []
        let ix = MediaFileIndexer(api: api, speech: FakeSpeech(.denied), transcriber: transcriber,
                                  sampler: FakeSampler())
        ix.say = { said.append($0) }
        let out = await ix.add([try file("memo.m4a")])
        XCTAssertEqual(transcriber.calls, 0)
        XCTAssertEqual(out, [.noWords(reason: Copy.mediaSpeechDenied)])
        XCTAssertEqual(api.bodies.count, 1, "kept, without words")
        XCTAssertEqual(said.last, Copy.mediaSpeechDenied)
    }

    func testNoSpeechModelIsSaidNeverDownloaded() async throws {
        let transcriber = FakeTranscriber()
        transcriber.outcome = .noSpeechModel
        let ix = MediaFileIndexer(api: FakeMediaAPI(), speech: FakeSpeech(.authorized), transcriber: transcriber,
                                  sampler: FakeSampler())
        let out = await ix.add([try file("memo.m4a")])
        XCTAssertEqual(out, [.noWords(reason: Copy.mediaNoSpeechModel)])
    }

    func testTheRouterHandsMediaToTheReaderAndNeverSniffsThem() throws {
        let api = FakeIntakeAPI()
        let router = IntakeRouter(api: api, home: dir)
        var handed: [URL] = []
        router.onMedia = { handed += $0 }
        let memo = try file("memo.m4a")
        XCTAssertEqual(router.accept(urls: [memo], from: .windowDrop), .accepted)
        XCTAssertEqual(handed, [memo])
        XCTAssertTrue(api.sniffed.isEmpty, "a recording is never sent to the import")
        let hidden = dir.appendingPathComponent(".claude")
        try FileManager.default.createDirectory(at: hidden, withIntermediateDirectories: true)
        let inside = hidden.appendingPathComponent("voice.m4a")
        try Data("x".utf8).write(to: inside)
        handed = []
        _ = router.accept(urls: [inside], from: .windowDrop)
        XCTAssertEqual(handed, [], "a recording under a refused root is never read")
    }

    func testTheInfoPlistSaysWhySpeechIsAskedFor() throws {
        let script = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: script, encoding: .utf8)
        XCTAssertTrue(text.contains("NSSpeechRecognitionUsageDescription"),
                      "without it macOS ends the app at the request instead of asking")
    }
}
