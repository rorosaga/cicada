import AVKit
import Foundation
import SwiftUI

/// The production `VideoPlaybackController` (R-V6). This is the ONLY file in
/// the app that imports AVFoundation — `AVImportLintTests` fails the build on
/// a second one — so every view, layout and key-handling decision above it is
/// unit-testable against `FakePlaybackController` with no player involved.
///
/// AVKit rather than WebKit is what makes local files and HLS work at all:
/// `WKWebView` refuses a `file://` document loaded via `URLRequest`, and will
/// not play a bare `.m3u8` manifest as a document.
///
/// The ToS rail (R-V4) is upstream of this file, not in it: the only URLs that
/// ever reach here are ones the USER saved as a direct file URL. Cicada never
/// derives a stream — no `yt-dlp`, no provider CDN URL, no `.m3u8` lifted out
/// of a page.
final class AVPlaybackController: VideoPlaybackController {
    let url: URL
    let player: AVPlayer
    var isPlaying: Bool { player.timeControlStatus != .paused }

    init(url: URL) {
        self.url = url
        // Starts PAUSED on purpose: a player that begins the moment an entity
        // page renders is the same surprise the hero embed deliberately avoids
        // (`MediaURLHelpers.youtubeHeroEmbedURL` — the hero never autoplays).
        self.player = AVPlayer(url: url)
    }

    func play() { player.play() }
    func pause() { player.pause() }
    func toggle() { isPlaying ? pause() : play() }
}

/// `AVPlayerView` with inline transport controls, wrapped so `VideoPlayerView`
/// stays AVFoundation-free.
///
/// It takes the **protocol**, not `AVPlaybackController`, and does the cast
/// here: `VideoPlayerView` holds a `VideoPlaybackController?` (that is the
/// whole point of R-V6), so if this surface demanded the concrete type the
/// view would have to name an AV type to build it and `AVImportLintTests`
/// would be linting a seam that no longer exists. A fake controller in a
/// preview or a test simply renders an empty player rather than crashing.
struct AVPlayerSurface: NSViewRepresentable {
    let controller: VideoPlaybackController

    private var player: AVPlayer? { (controller as? AVPlaybackController)?.player }

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .inline
        view.videoGravity = .resizeAspect
        view.player = player
        return view
    }

    func updateNSView(_ view: AVPlayerView, context: Context) {
        // Same rule as `WebView.updateNSView`: only swap when the player really
        // changed, so a re-render never restarts playback.
        if view.player !== player { view.player = player }
    }
}
