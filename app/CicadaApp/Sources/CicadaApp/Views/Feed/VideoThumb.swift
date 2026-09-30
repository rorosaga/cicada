import SwiftUI

/// G162 — a saved video's frame: the thumbnail the page already stores, with its length in a corner badge where the
/// provider reported one, or the neutral play tile when the page stores no thumbnail (or it cannot load: offline,
/// blocked). Only the stored URL is ever loaded — no thumbnail URL is derived from a video id (R-7, Track V).
struct VideoThumb: View {
    let thumbnail: String?
    let durationS: Int?
    let width: CGFloat
    let height: CGFloat
    var showsLength = true

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            if let thumbnail, let url = URL(string: thumbnail), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                AsyncImage(url: url) { phase in
                    if case .success(let image) = phase { image.resizable().scaledToFill() } else { playTile }
                }
            } else {
                playTile
            }
            if showsLength, let length = VideoRef.durationLabel(durationS) {
                Text(length)
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
                    .monospacedDigit()
                    .foregroundStyle(Color.white)
                    .padding(.horizontal, CicadaTheme.scaled(3))
                    .background(CicadaTheme.shape(2).fill(Color.black.opacity(0.72)))
                    .padding(CicadaTheme.scaled(2))
            }
        }
        .frame(width: CicadaTheme.scaled(width), height: CicadaTheme.scaled(height))
        .clipShape(CicadaTheme.shape(CicadaTheme.radiusXS))
        .accessibilityHidden(true)
    }

    private var playTile: some View {
        ZStack {
            CicadaTheme.bgSelected
            Image(systemName: "play.fill")
                .font(CicadaTheme.font(size: 10, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

/// The picker's "channel · length" line with the provider's own 12 pt mark where one is bundled (YouTube), or its
/// name in text where it is not (Vimeo, Loom — P12).
struct VideoChannelLine: View {
    let item: MediaFeedItem
    var color: Color = CicadaTheme.textTertiary

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(5)) {
            if VideoWords.showsYouTubeMark(item), LogoImage.exists(name: "youtube") {
                LogoImage(name: "youtube", size: CicadaTheme.scaled(12))
            }
            Text(line)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(color)
                .lineLimit(1)
        }
    }

    private var line: String { VideoWords.pickerLine(item) }
}
