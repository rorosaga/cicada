import SwiftUI
import WebKit

// MARK: - WebView (G11, Track V)
//
// A thin, reusable `NSViewRepresentable` over `ClickableWebView` (defined in
// GraphView.swift) that loads a SINGLE url. Used for the in-app site preview
// and for a provider's own embedded player (YouTube, Vimeo, TikTok, Loom).
//
// SECURITY: the caller only ever passes the media entity's OWN stored
// `media.url` (for website previews) or the embed url DERIVED from that stored
// url by `VideoRef` — derived, never fetched and never lifted out of a
// provider's returned HTML (R-V4). This view never takes arbitrary request
// input from anywhere else — there are no message handlers and no JS bridge,
// which is also why space-to-play is a `VideoPlayerView` affordance only
// (R10): inside here the key belongs to the provider's player.
struct WebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // Allow inline media playback (provider embeds) without forcing fullscreen.
        config.mediaTypesRequiringUserActionForPlayback = []
        let webView = ClickableWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        load(url, into: webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Reload only when the target url actually changes — avoids reloading
        // (and restarting a video) on every SwiftUI re-render.
        if webView.url?.absoluteString != url.absoluteString {
            load(url, into: webView)
        }
    }

    /// WebKit refuses a `file://` document loaded through `URLRequest` — it
    /// needs `loadFileURL(_:allowingReadAccessTo:)` with an explicit read
    /// scope, which is why a local clip rendered as a blank frame before
    /// R-V3. Read access is granted to the file's own directory and no wider:
    /// a WebView in this app only ever loads the media entity's own url.
    ///
    /// A local *video* takes the AVKit path (`VideoPlayerView`), not this one,
    /// because `WKWebView` will not play a bare `.m3u8` manifest as a
    /// top-level document either; this branch is what makes any other
    /// `file://` document the app is handed render at all.
    private func load(_ url: URL, into webView: WKWebView) {
        if url.isFileURL {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        } else {
            webView.load(URLRequest(url: url))
        }
    }
}

// MARK: - WebPreviewSheet
//
// A framed overlay that hosts a `WebView` with a title bar and a close + open-
// externally affordance. Presented as a `.sheet` from the media preview's
// "Preview site" / "Play" actions.
struct WebPreviewSheet: View {
    let title: String
    let url: URL
    /// The original external url to hand off to the system browser. For a
    /// provider embed this is the `VideoRef`'s watch url, not the embed url,
    /// so "Open externally" lands on the real page.
    let externalURL: URL
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)

                Spacer()

                Button {
                    NSWorkspace.shared.open(externalURL)
                } label: {
                    Label("Open externally", systemImage: "arrow.up.right.square")
                        .font(CicadaTheme.font(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .buttonStyle(.cicadaPlain)
                .help("Open in your browser")

                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.cicadaPlain)
            }
            .padding(CicadaTheme.spacingLG)

            Divider().background(CicadaTheme.border)

            WebView(url: url)
        }
        .frame(width: 900, height: 620)
        .background(CicadaTheme.background)
    }
}
