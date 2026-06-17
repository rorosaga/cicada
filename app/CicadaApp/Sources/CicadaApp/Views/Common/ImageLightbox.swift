import SwiftUI

// MARK: - ImageThumbnail (G11)
//
// A small, rounded, tappable inline image. On tap it presents an `ImageLightbox`
// overlay showing the image large with zoom. Reused by `MediaPreview` (media
// entities) and by `TranscludingMarkdownView` (inline `![alt](url)` images).
struct ImageThumbnail: View {
    let url: URL
    var width: CGFloat = 320
    var height: CGFloat = 180
    var cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall

    @State private var showLightbox = false
    @State private var isHovered = false

    var body: some View {
        Button { showLightbox = true } label: {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    placeholder(symbol: "photo")
                case .empty:
                    ZStack {
                        CicadaTheme.surfaceHover
                        ProgressView().controlSize(.small)
                    }
                @unknown default:
                    placeholder(symbol: "photo")
                }
            }
            .frame(width: width, height: height)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
            .overlay(alignment: .bottomTrailing) {
                Image(systemName: "arrow.up.left.and.arrow.down.right")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(5)
                    .background(.black.opacity(0.45))
                    .clipShape(RoundedRectangle(cornerRadius: 5))
                    .padding(6)
                    .opacity(isHovered ? 1 : 0)
            }
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .help("Click to enlarge")
        .sheet(isPresented: $showLightbox) {
            ImageLightbox(url: url)
        }
    }

    private func placeholder(symbol: String) -> some View {
        ZStack {
            CicadaTheme.mediaPink.opacity(0.1)
            Image(systemName: symbol)
                .font(.system(size: 24))
                .foregroundStyle(CicadaTheme.mediaPink.opacity(0.6))
        }
    }
}

// MARK: - ImageLightbox
//
// Full-size image overlay with scroll-to-zoom and an ✕ to dismiss. Loads only
// the url it is handed (always the media entity's own stored/thumbnail url).
struct ImageLightbox: View {
    let url: URL
    @Environment(\.dismiss) private var dismiss
    @State private var zoom: CGFloat = 1.0
    @State private var committedZoom: CGFloat = 1.0

    var body: some View {
        ZStack {
            Color.black.opacity(0.92)
                .onTapGesture { dismiss() }

            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFit()
                        .scaleEffect(zoom)
                        .gesture(
                            MagnificationGesture()
                                .onChanged { value in
                                    // Accumulate against the last committed zoom so
                                    // repeated pinches don't snap back to 1x.
                                    zoom = max(1.0, min(5.0, committedZoom * value))
                                }
                                .onEnded { _ in
                                    committedZoom = zoom
                                }
                        )
                case .failure:
                    VStack(spacing: CicadaTheme.spacingSM) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 32))
                        Text("Couldn't load image")
                            .font(CicadaTheme.bodyFont)
                    }
                    .foregroundStyle(CicadaTheme.textSecondary)
                case .empty:
                    ProgressView().controlSize(.large)
                @unknown default:
                    EmptyView()
                }
            }
            .padding(CicadaTheme.spacingXL)

            VStack {
                HStack {
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.white)
                            .frame(width: 34, height: 34)
                            .background(.black.opacity(0.5))
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }
        }
        .frame(minWidth: 600, minHeight: 440)
        .frame(width: 880, height: 640)
    }
}
