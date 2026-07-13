import SwiftUI
import WebKit

// MARK: - WebView (G11)
//
// A thin, reusable `NSViewRepresentable` over `ClickableWebView` (defined in
// GraphView.swift) that loads a SINGLE url. Used for the in-app site preview
// and the embedded YouTube player.
//
// SECURITY: the caller only ever passes the media entity's OWN stored
// `media.url` (for website previews) or the YouTube embed url DERIVED from that
// stored url (see `MediaPreview`). This view never takes arbitrary request
// input from anywhere else — there are no message handlers and no JS bridge.
struct WebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // Allow inline media playback (YouTube embeds) without forcing fullscreen.
        config.mediaTypesRequiringUserActionForPlayback = []
        let webView = ClickableWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Reload only when the target url actually changes — avoids reloading
        // (and restarting a video) on every SwiftUI re-render.
        if webView.url?.absoluteString != url.absoluteString {
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
    /// YouTube embed this is the watch url, not the embed url, so "Open
    /// externally" lands on the real page.
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
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .buttonStyle(.plain)
                .help("Open in your browser")

                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
            }
            .padding(CicadaTheme.spacingLG)

            Divider().background(CicadaTheme.border)

            WebView(url: url)
        }
        .frame(width: 900, height: 620)
        .background(CicadaTheme.background)
    }
}
