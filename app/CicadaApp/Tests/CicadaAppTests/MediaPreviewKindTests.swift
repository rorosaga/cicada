import XCTest
@testable import CicadaApp

/// R-V1 / plan R7: the URL decides, `mediaType` is a hint. Every case below
/// is a page shape that exists on a real bank today — the browser-sync path
/// stamps `bookmark` on everything it imports, and the TikTok export path
/// stamps `url`, which is exactly why dispatching on `mediaType` meant those
/// items could never play.
final class MediaPreviewKindTests: XCTestCase {
    private func model(_ url: String, _ mediaType: String) -> MediaPreviewModel {
        MediaPreviewModel(block: MediaBlock(url: url, mediaType: mediaType), title: "t")
    }

    func testALegacyBookmarkTypedVimeoPageStillPlays() {
        guard case .embedVideo(let ref) = model("https://vimeo.com/123456789", "bookmark").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.provider, .vimeo)
        XCTAssertEqual(ref.embedURL?.absoluteString, "https://player.vimeo.com/video/123456789")
    }

    func testAUrlTypedTikTokExportItemStillPlays() {
        guard case .embedVideo(let ref) = model("https://www.tiktok.com/@exampleuser/video/1234567890123456789", "url").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.provider, .tiktok)
    }

    func testAYouTubePlaylistResolvesToTheVideoseriesEmbed() {
        guard case .embedVideo(let ref) = model("https://www.youtube.com/playlist?list=PLexample01", "youtube").kind
        else { return XCTFail("expected .embedVideo") }
        XCTAssertEqual(ref.embedURL?.absoluteString,
                       "https://www.youtube-nocookie.com/embed/videoseries?list=PLexample01")
    }

    func testAYouTubeLiveURLResolves() {
        guard case .embedVideo = model("https://www.youtube.com/live/vid00000003", "youtube").kind
        else { return XCTFail("expected .embedVideo") }
    }

    func testADirectFileIsAFileVideoNotAWebsite() {
        guard case .fileVideo(let ref) = model("https://example.com/media/clip.mp4", "bookmark").kind
        else { return XCTFail("expected .fileVideo") }
        XCTAssertEqual(ref.provider, .direct)
    }

    func testALocalFileIsAFileVideo() {
        guard case .fileVideo(let ref) = model("file:///Users/example/Movies/clip.mov", "url").kind
        else { return XCTFail("expected .fileVideo") }
        XCTAssertEqual(ref.provider, .local)
    }

    func testInstagramStaysInstagramWhateverTheMediaTypeSays() {
        XCTAssertEqual(model("https://www.instagram.com/reel/Cexample01/", "bookmark").kind, .instagram)
        XCTAssertEqual(model("https://www.instagram.com/p/Cexample02/", "instagram").kind, .instagram)
    }

    func testAnExternalOnlyProviderGetsNoNewCase() {
        // R6: Twitch is recognised as a video and deliberately not played —
        // there is nothing new to offer, so it stays the website card it is.
        XCTAssertEqual(model("https://www.twitch.tv/videos/1234567890", "bookmark").kind, .website)
        XCTAssertEqual(model("https://vm.tiktok.com/ZMexample/", "url").kind, .website)
    }

    func testAYouTubeTypedPageWithNoVideoIdFallsBackToTheWebsiteCard() {
        // "Preview site" is the honest label for a channel page.
        XCTAssertEqual(model("https://www.youtube.com/@examplechannel", "youtube").kind, .website)
    }

    func testAnImageIsStillAnImage() {
        XCTAssertEqual(model("https://example.com/photo.jpg", "bookmark").kind, .image)
    }
}
