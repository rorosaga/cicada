import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import CicadaApp

/// ROR-117 / G43 — an added recording, video or photo plays or shows in the app. Decisions made before a player
/// exists (R-V6): where a hit lands, which surface, what a moved file says, what closing does. Fixtures only; no
/// AVPlayer is built and no prompt is raised.
@MainActor
final class MediaViewerTests: XCTestCase {
    private var dir: URL!
    private let places = MediaFilePlaces(defaults: UserDefaults(suiteName: "viewer-places-\(UUID().uuidString)")!)

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("viewer-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir) }

    private func file(_ name: String, _ body: String = "stand-in bytes") throws -> URL {
        let url = dir.appendingPathComponent(name)
        try Data(body.utf8).write(to: url)
        return url
    }

    /// A real, tiny PNG: the photo door decodes it with ImageIO.
    private func png(_ name: String, width: Int = 1600, height: Int = 900) throws -> URL {
        let url = dir.appendingPathComponent(name)
        let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        ctx.setFillColor(CGColor(red: 0.2, green: 0.5, blue: 0.7, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
        XCTAssertTrue(CGImageDestinationFinalize(dest))
        return url
    }

    // MARK: Where a hit lands

    func testAHitCarriesItsSecondThroughToThePlayer() throws {
        let memo = try file("memo.m4a")
        places.remember("0123456789abcdef", memo)
        XCTAssertEqual(MediaViewerModel.target(id: "0123456789abcdef", at: 125, places: places),
                       .play(url: memo, kind: .audio, start: 125))
        let clip = try file("clip.mp4")
        places.remember("fedcba9876543210", clip)
        XCTAssertEqual(MediaViewerModel.target(id: "fedcba9876543210", at: 63.5, places: places),
                       .play(url: clip, kind: .video, start: 63.5))
    }

    func testThePalettesDestinationReachesTheSheetWithItsSecond() {
        let router = AppRouter()
        router.openMedia(id: "0123456789abcdef", at: 125)
        XCTAssertEqual(router.mediaRoute, .file(id: "0123456789abcdef", at: 125))
        router.openAddedFiles()
        XCTAssertEqual(router.mediaRoute, .list)
    }

    func testAHitWithNoSecondStartsAtTheBeginning() {
        XCTAssertEqual(MediaViewerModel.start(nil), 0)
        XCTAssertEqual(MediaViewerModel.start(-4), 0)
        XCTAssertEqual(MediaViewerModel.start(.nan), 0)
        XCTAssertEqual(MediaViewerModel.start(.infinity), 0)
        XCTAssertEqual(MediaViewerModel.start(9), 9)
    }

    func testAPhotoOpensTheViewerNotAPlayer() throws {
        let photo = try png("trip.png")
        places.remember("aaaaaaaaaaaaaaaa", photo)
        XCTAssertEqual(MediaViewerModel.target(id: "aaaaaaaaaaaaaaaa", at: nil, places: places), .photo(url: photo))
        // A frame-time on a photo is ignored: there is no time in a picture.
        XCTAssertEqual(MediaViewerModel.target(id: "aaaaaaaaaaaaaaaa", at: 30, places: places), .photo(url: photo))
    }

    // MARK: A file that is not there

    func testAMovedOrDeletedFileSaysSoInsteadOfAPlayer() throws {
        let memo = try file("memo.m4a")
        places.remember("0123456789abcdef", memo)
        try FileManager.default.removeItem(at: memo)
        XCTAssertEqual(MediaViewerModel.target(id: "0123456789abcdef", at: 5, places: places), .missing)
        XCTAssertEqual(Copy.mediaGone, "That file isn't on this Mac.")
    }

    func testAFileKnownFromAnotherDeviceIsMissingToo() {
        XCTAssertEqual(MediaViewerModel.target(id: "ffffffffffffffff", at: 5, places: places), .missing)
    }

    func testAFileIsRecognisedByItsBytesAndAStoresItemCannotBeRepointed() throws {
        let original = try file("a.m4a", "the original recording")
        let id = String(try XCTUnwrap(MediaFileIndexer.sha256(of: original)).prefix(16))
        let copy = try file("b.m4a", "the original recording")
        let other = try file("c.m4a", "something else")
        XCTAssertTrue(MediaViewerModel.isTheFile(copy, id: id, source: nil), "a moved file chosen again")
        XCTAssertFalse(MediaViewerModel.isTheFile(other, id: id, source: nil))
        XCTAssertFalse(MediaViewerModel.isTheFile(copy, id: id, source: "voice_memos"), "a memo's id is the store's")
    }

    // MARK: Closing

    func testOpeningPlaysFromTheSecondAndClosingStops() {
        let c = FakePlaybackController(url: URL(fileURLWithPath: "/x/memo.m4a"))
        MediaViewerModel.begin(c, at: 125)
        XCTAssertEqual(c.currentTime, 125)
        XCTAssertTrue(c.isPlaying)
        MediaViewerModel.end(c)
        XCTAssertFalse(c.isPlaying)
        XCTAssertEqual(c.stops, 1)
        MediaViewerModel.end(nil)   // a surface that never built a player closes quietly
    }

    func testTheClockReadsLikeTheHitsSubtitle() {
        XCTAssertEqual(MediaViewerModel.clock(0), "0:00")
        XCTAssertEqual(MediaViewerModel.clock(125), "2:05")
        XCTAssertEqual(MediaViewerModel.clock(3725), "1:02:05")
        XCTAssertEqual(MediaViewerModel.clock(.nan), "0:00")
    }

    func testThePhotoViewerKeepsItsZoomInRange() {
        XCTAssertEqual(PhotoViewer.clamp(0.2), 1)
        XCTAssertEqual(PhotoViewer.clamp(3), 3)
        XCTAssertEqual(PhotoViewer.clamp(40), 6)
    }

    // MARK: A photo comes in

    func testAPhotoIsAKindOfAddedFileButAnSVGIsNot() throws {
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/trip.png")), .image)
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/trip.jpeg")), .image)
        XCTAssertEqual(MediaKind.of(URL(fileURLWithPath: "/x/trip.heic")), .image)
        XCTAssertNil(MediaKind.of(URL(fileURLWithPath: "/x/logo.svg")))
        let photo = try png("trip.png")
        XCTAssertEqual(MediaFileIndexer.media(in: [photo]), [photo])
        XCTAssertTrue(IntakePicker.mediaContentTypes.contains(.image))
    }

    func testAPhotoPostsOneSmallDerivativeAndAsksForNoSpeech() async throws {
        let photo = try png("trip.png")
        let api = FakeMediaAPI()
        let speech = FakeSpeech(.notDetermined)
        let transcriber = FakeTranscriber()
        let sampler = FakeSampler()
        let ix = MediaFileIndexer(api: api, speech: speech, transcriber: transcriber, sampler: sampler, places: places)
        var said: [String] = []
        ix.say = { said.append($0) }
        let out = await ix.add([photo])
        XCTAssertEqual(out, [.addedPhoto])
        XCTAssertEqual(api.bodies.count, 1)
        XCTAssertEqual(api.bodies[0]["kind"] as? String, "image")
        XCTAssertEqual(api.bodies[0]["name"] as? String, "trip.png")
        XCTAssertNil(api.bodies[0]["path"], "the backend never learns a path")
        XCTAssertEqual((api.bodies[0]["segments"] as? [Any])?.count, 0, "a photo has no words")
        XCTAssertEqual(api.frames, [1], "one derivative")
        XCTAssertEqual(speech.requests, 0, "a photo never raises the Speech prompt")
        XCTAssertEqual(transcriber.calls + sampler.calls, 0)
        XCTAssertEqual(places.url(of: "0123456789abcdef")?.path, photo.path, "the viewer opens it from here")
        XCTAssertEqual(said.last, "Added to search.")
    }

    func testThePhotoDerivativeFitsTheFrameBox() throws {
        let frame = try XCTUnwrap(MediaFrames.photoFrame(try png("wide.png", width: 4000, height: 3000)))
        XCTAssertEqual(frame.t, 0)
        XCTAssertLessThanOrEqual(frame.jpeg.count, 200 * 1024)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(frame.jpeg as CFData, nil))
        let props = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertLessThanOrEqual(props[kCGImagePropertyPixelWidth] as? Int ?? 9999, MediaFrames.maxWidth)
        XCTAssertLessThanOrEqual(props[kCGImagePropertyPixelHeight] as? Int ?? 9999, MediaFrames.maxHeight)
        XCTAssertNil(MediaFrames.photoFrame(try file("broken.png", "not a picture")))
    }

    func testAPhotoThatCannotBeDecodedFailsInWords() async throws {
        let ix = MediaFileIndexer(api: FakeMediaAPI(), speech: FakeSpeech(.authorized), transcriber: FakeTranscriber(),
                                  sampler: FakeSampler(), places: places)
        let out = await ix.add([try file("broken.png", "not a picture")])
        XCTAssertEqual(out, [.failed])
    }

    // MARK: The list

    func testTheListRowOpensTheSameFileAHitDoes() throws {
        let json = #"{"files":[{"id":"0123456789abcdef","name":"talk.mov","kind":"video","duration_s":125,"added_at":"2026-11-05T10:00:00+00:00"},"#
            + #"{"id":"aaaaaaaaaaaaaaaa","name":"trip.png","kind":"image"},"#
            + #"{"id":"bbbbbbbbbbbbbbbb","name":"Memo","kind":"audio","source":"voice_memos","recorded_at":"2026-03-04T09:15:00+00:00"}]}"#
        let files = try JSONDecoder().decode(AddedFilesResponse.self, from: Data(json.utf8)).files
        XCTAssertEqual(files.map(\.glyph), ["film", "photo", "waveform"])
        XCTAssertEqual(files.map(\.detail), ["2:05", nil, nil])
        XCTAssertEqual(files[2].source, "voice_memos")
        // The list's row sets the sheet's route the way a hit does: the file's id, no second.
        let clip = try file("talk.mov")
        places.remember(files[0].id, clip)
        XCTAssertEqual(MediaViewerModel.target(id: files[0].id, at: nil, places: places),
                       .play(url: clip, kind: .video, start: 0))
        XCTAssertEqual(MediaRoute.file(id: files[0].id, at: nil).id, "file:0123456789abcdef")
    }

    func testAPhotoHitIsAPhotoRowAndAFrameHitOpensItsRecordingAtThatSecond() throws {
        let wire = """
        {"results": [
          {"id": "photo:aaaaaaaaaaaaaaaa", "name": "trip.png", "type": "image", "status": "active", "confidence": 0,
           "score": 0.3, "snippet": "", "kind": "image", "matchedField": "semantic", "imageSource": "photo",
           "fileId": "aaaaaaaaaaaaaaaa", "thumbnail": "/files/aaaaaaaaaaaaaaaa/frames/0"},
          {"id": "frame:fedcba9876543210@63000", "name": "talk.mov at 1:03", "type": "image", "status": "active",
           "confidence": 0, "score": 0.12, "snippet": "", "kind": "image", "matchedField": "semantic",
           "imageSource": "frame", "fileId": "fedcba9876543210", "atSeconds": 63.0}
        ], "totals": {}, "mode": "hybrid", "indexState": "ready"}
        """
        let rows = FindServerRows.rows(FakeFindSearch.decode(wire), query: "trip", context: .init())
        let photo = try XCTUnwrap(rows.first { $0.badge == "Photo" })
        XCTAssertEqual(photo.destination, .addedFile(id: "aaaaaaaaaaaaaaaa", at: nil))
        XCTAssertEqual(photo.detail, Copy.findPhotoDetail)
        XCTAssertEqual(FindRowText.kindLabel(photo), "Photo")
        let frame = try XCTUnwrap(rows.first { $0.badge == "Video" })
        XCTAssertEqual(frame.destination, .addedFile(id: "fedcba9876543210", at: 63))
        let clip = try file("talk.mov")
        places.remember("fedcba9876543210", clip)
        XCTAssertEqual(MediaViewerModel.target(id: "fedcba9876543210", at: 63, places: places),
                       .play(url: clip, kind: .video, start: 63), "a frame hit opens its recording at that second")
    }
}
