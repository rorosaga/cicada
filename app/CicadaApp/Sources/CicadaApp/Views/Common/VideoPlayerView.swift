import SwiftUI

// MARK: - VideoPlaybackController (Track V, R-V6)

/// The seam between "a video is on screen" and "AVFoundation is running it".
///
/// R-V6: `AVPlaybackController.swift` is the ONLY file in the app allowed to
/// import AVFoundation, and `AVImportLintTests` fails the build on a second
/// one. Everything above this protocol — which controller to keep across a
/// re-render, whether the space key was handled, whether a local file is even
/// readable — is a decision made *before* a player exists, so it is unit-tested
/// against a fake with no `AVPlayer` ever constructed. What is NOT testable
/// this way ("does this codec decode?") is a stated manual check rather than a
/// mocked green: a mock that answers a codec question answers it wrongly.
///
/// `AnyObject` on purpose: identity is the contract. `VideoPlayerModel`
/// decides whether to KEEP a controller, and "keep" only means anything for a
/// reference type — a struct copy would restart playback on every re-render,
/// which is exactly the bug `WebView.updateNSView` already guards against for
/// the embed path.
protocol VideoPlaybackController: AnyObject {
    var url: URL { get }
    var isPlaying: Bool { get }
    func play()
    func pause()
    func toggle()
}

// MARK: - VideoPlayerModel

/// The pure half of the player: no view, no AVFoundation, no `@State`.
///
/// Every rule the player has to get right lives here as a total function of its
/// arguments, so the regression net is a plain XCTest against
/// `FakePlaybackController` rather than a rendered-view assertion.
enum VideoPlayerModel {
    /// What the view should show for a URL — decided BEFORE a controller is
    /// built, because an `AVPlayer` over an unreadable path renders a black
    /// rectangle and says nothing (R9).
    enum State: Equatable {
        case playable(URL)
        /// The path is carried, not just a flag: the card names the file and
        /// offers to reveal it, which is the whole point of not showing black.
        case unreadable(path: String)
    }

    /// R9 — an unreadable local file shows the fix, never a black rectangle.
    ///
    /// A remote URL is always `.playable`: reachability is the network's
    /// answer to give at load time, not something to pre-judge here (and this
    /// function does no I/O beyond the local `stat`). A `file://` URL is gated
    /// on `isReadableFile(atPath:)` — the cheap check that catches the two
    /// cases that actually happen: the clip moved, or an external volume is
    /// not mounted.
    ///
    /// This is a READABILITY gate, not a decode gate. Whether AVFoundation can
    /// decode the bytes behind a readable path is the manual check (R8); the
    /// answer to *that* is AVKit's own error UI, never a black rectangle.
    ///
    /// **Known limit, disclosed rather than filed as a TODO:** the app is
    /// unsandboxed today, so `isReadableFile` is the whole truth. If Cicada is
    /// ever sandboxed, a `file://` outside the container would need a
    /// security-scoped bookmark minted where the user picked the file — this
    /// check would then report "unreadable" for a file the user can plainly
    /// see, and the fix belongs at the picker, not here.
    static func state(for url: URL) -> State {
        guard url.isFileURL else { return .playable(url) }
        return FileManager.default.isReadableFile(atPath: url.path)
            ? .playable(url)
            : .unreadable(path: url.path)
    }

    /// Controller identity across re-renders: keep the existing one when it is
    /// already pointed at this URL, build a new one when it is not.
    ///
    /// SwiftUI re-runs `body` for reasons that have nothing to do with the
    /// video (a theme scale change, a parent's state, a sync tick). Rebuilding
    /// the player on each of those restarts playback from zero — the same
    /// defect `WebView.updateNSView` guards by comparing URLs before reloading.
    /// `make` is injected so the tests can build a fake; production passes
    /// `AVPlaybackController.init`.
    static func controller(
        for url: URL,
        existing: VideoPlaybackController?,
        make: (URL) -> VideoPlaybackController
    ) -> VideoPlaybackController {
        if let existing, existing.url == url { return existing }
        return make(url)
    }

    /// R10 — space toggles play for a file video only, and only when there is
    /// something to toggle.
    ///
    /// Returns whether the key was consumed, so the caller can answer
    /// `.handled` / `.ignored`. Swallowing the key with no controller would
    /// eat a space the rest of the window still wants (the Feed's search field
    /// is one keystroke away), which is why this is scoped to the player
    /// container and never a global `.keyboardShortcut(" ")`.
    @discardableResult
    static func handleSpace(_ controller: VideoPlaybackController?) -> Bool {
        guard let controller else { return false }
        controller.toggle()
        return true
    }
}

// MARK: - VideoPlayerView

/// A real transport-controlled player for a direct or local video file
/// (R-V3). Takes a bare `URL`, not a `VideoRef`, so anything with a playable
/// file URL can host one.
///
/// AVKit rather than the existing `WebView` is what makes this work at all:
/// `WKWebView` refuses a `file://` document loaded through `URLRequest`, and
/// will not play a bare `.m3u8` manifest as a top-level document.
struct VideoPlayerView: View {
    let url: URL

    /// Held as the PROTOCOL, never the concrete class — that is the R-V6 seam.
    /// Naming `AVPlaybackController` as the stored type here would pull an AV
    /// type into this file's signature and the lint would be guarding a seam
    /// that no longer exists.
    @State private var controller: VideoPlaybackController?

    var body: some View {
        Group {
            switch VideoPlayerModel.state(for: url) {
            case .playable:
                if let controller {
                    AVPlayerSurface(controller: controller)
                } else {
                    // The one frame between `body` and `.task` firing. A
                    // paused player looks like this anyway.
                    CicadaTheme.surfaceHover
                }
            case .unreadable(let path):
                unreadableCard(path: path)
            }
        }
        .task(id: url) {
            // Assigned HERE, never from inside `body`: mutating `@State`
            // during a view update is the SwiftUI defect that produces
            // "Modifying state during view update" and an undefined render.
            // `.task(id:)` re-fires exactly when the url changes, which is the
            // swap `VideoPlayerModel.controller` decides.
            controller = VideoPlayerModel.controller(
                for: url, existing: controller, make: AVPlaybackController.init
            )
        }
        .focusable()
        .onKeyPress(.space) {
            // R10: scoped to this container. A global `.keyboardShortcut(" ")`
            // would eat the Feed's search field. Inside a `WKWebView` the key
            // belongs to the provider's player and cannot be intercepted
            // without a JS bridge, which `WebView` deliberately does not have
            // — so space is a file-video affordance only.
            VideoPlayerModel.handleSpace(controller) ? .handled : .ignored
        }
    }

    /// R9's card: name the file, offer the two things that actually help.
    /// "Open externally" for a local file means Finder, not a browser.
    @ViewBuilder
    private func unreadableCard(path: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.warning)
                Text("Cicada can't read this file")
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            Text(path)
                .font(CicadaTheme.monoFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(3)
                .textSelection(.enabled)
            Text("It may have moved, been renamed, or live on a volume that isn't mounted.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)

            HStack(spacing: CicadaTheme.spacingMD) {
                Button {
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                } label: {
                    Label("Reveal in Finder", systemImage: "folder")
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.accent)
                }
                .buttonStyle(.cicadaPlain)
                .help("Show the file in Finder")

                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    Label("Open externally", systemImage: "arrow.up.right.square")
                        .font(CicadaTheme.font(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Hand the file to the system")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.surface)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
    }
}
