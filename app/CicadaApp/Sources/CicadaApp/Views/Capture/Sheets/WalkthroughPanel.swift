import AVKit
import AppKit
import SwiftUI

/// The export walkthrough shown inside the "+" sheet (G64): pick a vendor, read
/// three or four steps, jump straight to that vendor's export settings page,
/// then drop the file. The 16:9 area plays `Resources/walkthroughs/<vendor>.mp4`
/// when one has been recorded (muted, looping) and shows a static placeholder
/// otherwise — the recordings are a separate manual pass, see
/// docs/walkthrough-recording.md.
enum WalkthroughVendor: String, CaseIterable, Identifiable {
    case claude, chatgpt, takeout, instagram

    var id: String { rawValue }

    var title: String {
        switch self {
        case .claude: "Claude"
        case .chatgpt: "ChatGPT"
        case .takeout: "Google Takeout"
        case .instagram: "Instagram"
        }
    }

    /// The page that actually holds the export button. Opened with
    /// `NSWorkspace.shared.open` — no deep-link scheme, just the web settings.
    var exportURL: URL {
        switch self {
        case .claude: URL(string: "https://claude.ai/settings/data-privacy-controls")!
        case .chatgpt: URL(string: "https://chatgpt.com/#settings/DataControls")!
        case .takeout: URL(string: "https://takeout.google.com/")!
        case .instagram: URL(string: "https://accountscenter.instagram.com/info_and_permissions/dyi/")!
        }
    }

    var steps: [String] {
        switch self {
        case .claude: [
            "Open Settings → Privacy on claude.ai.",
            "Click “Export data” and confirm.",
            "Anthropic emails you a .zip — unzip it.",
            "Drop conversations.json here.",
        ]
        case .chatgpt: [
            "Open Settings → Data controls on chatgpt.com.",
            "Click “Export data” and confirm.",
            "OpenAI emails you a .zip — unzip it.",
            "Drop conversations.json here.",
        ]
        case .takeout: [
            "Open Google Takeout and click “Deselect all”.",
            "Select YouTube, then limit it to “playlists” and “history”.",
            "Export as a .zip and download it.",
            "Drop the .zip here — Cicada reads the playlists and watch history.",
        ]
        case .instagram: [
            "Open Accounts Center → Your information and permissions.",
            "Choose “Download your information”, JSON format.",
            "Instagram emails you a link — download and unzip it.",
            "Drop saved_posts.json here.",
        ]
        }
    }

    /// Base name of the bundled recording, if one exists.
    var videoName: String { rawValue }

    /// The one-line "what this gets you" under the picker.
    var summary: String {
        switch self {
        case .claude: "Every Claude conversation, backdated to when it happened."
        case .chatgpt: "Every ChatGPT conversation, backdated to when it happened."
        case .takeout: "Your YouTube playlists and watch history as saved links."
        case .instagram: "Your saved Instagram posts as saved links."
        }
    }
}

struct WalkthroughPanel: View {
    /// The vendors this panel may offer — supplied by the tile, never
    /// `WalkthroughVendor.allCases`.
    let vendors: [WalkthroughVendor]
    @Binding var vendor: WalkthroughVendor
    let onChooseFile: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Picker("Export from", selection: $vendor) {
                ForEach(vendors) { v in
                    Text(v.title).tag(v)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityLabel("Choose which service to export from")

            Text(vendor.summary)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)

            stage

            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(Array(vendor.steps.enumerated()), id: \.offset) { index, step in
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Text("\(index + 1)")
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(CicadaTheme.accent)
                            .frame(width: 14, alignment: .trailing)
                        Text(step)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                Button {
                    NSWorkspace.shared.open(vendor.exportURL)
                } label: {
                    Label("Open \(vendor.title) export settings", systemImage: "arrow.up.forward.app")
                        .font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(.borderedProminent)
                .accessibilityLabel("Open \(vendor.title) export settings in your browser")

                Button("Choose file…", action: onChooseFile)
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Choose the exported file to import")
            }
        }
    }

    /// Reserved 16:9 area: the recording when it ships, a labelled placeholder
    /// until then. Sized by aspect ratio so the panel doesn't jump when a video
    /// is dropped in later.
    @ViewBuilder
    private var stage: some View {
        ZStack {
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(CicadaTheme.surfaceElevated)
            if let url = Self.videoURL(for: vendor) {
                LoopingVideo(url: url)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            } else {
                VStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "play.rectangle")
                        .font(.system(size: 22))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("Walkthrough video coming soon")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .aspectRatio(16.0 / 9.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .accessibilityLabel("\(vendor.title) export walkthrough")
    }

    static func videoURL(for vendor: WalkthroughVendor) -> URL? {
        Bundle.module.url(forResource: vendor.videoName, withExtension: "mp4",
                          subdirectory: "Resources/walkthroughs")
    }
}

/// Muted, looping, chrome-less player for a bundled walkthrough clip.
private struct LoopingVideo: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> AVPlayerView {
        let item = AVPlayerItem(url: url)
        let queue = AVQueuePlayer(items: [item])
        queue.isMuted = true
        context.coordinator.looper = AVPlayerLooper(player: queue, templateItem: item)
        let view = AVPlayerView()
        view.controlsStyle = .none
        view.videoGravity = .resizeAspect
        view.player = queue
        queue.play()
        return view
    }

    func updateNSView(_ nsView: AVPlayerView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var looper: AVPlayerLooper?
    }
}
