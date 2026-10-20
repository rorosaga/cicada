import AppKit
import SwiftUI

// MARK: - ImageThumbnail (G11; owner rulings 2026-10-14)
//
// A small, rounded, tappable picture. On tap it presents an `ImageLightbox` with the picture large and zoomable.
//
// **It loads only a picture Cicada stores** — a path on Cicada's own API (`/entities/…`, `/design/…`), through
// `PictureStore` with the bearer (`StoredPreviewPath`). It used to hand any https URL written into a page's prose to
// `AsyncImage`: the app made its own network call to whatever host an agent wrote, outside the picture gate and its
// "fetched once, then served from the store" rule. A web image in prose now draws as a bookmark of its URL
// (`ProseImage`), and `AsyncImageLintTests` keeps `AsyncImage` out of every surface that draws a page.
struct ImageThumbnail: View {
    /// A picture path on Cicada's API. Anything else draws the placeholder and loads nothing.
    let path: String
    var width: CGFloat = 320
    var height: CGFloat = 180
    var caption: String? = nil
    var cornerRadius: CGFloat = CicadaTheme.cornerRadiusSmall

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?
    @State private var showLightbox = false
    @State private var isHovered = false

    var body: some View {
        Button { if image != nil { showLightbox = true } } label: {
            ZStack {
                if let image {
                    Image(nsImage: image).resizable().scaledToFill()
                } else {
                    CicadaTheme.bgPane
                    Image(systemName: "photo")
                        .font(CicadaTheme.font(size: 24))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(width: width, height: height)
            .clipShape(CicadaTheme.shape(cornerRadius))
            .ringed(.resting, in: CicadaTheme.shape(cornerRadius))
            .overlay(alignment: .bottomTrailing) {
                Image(systemName: "arrow.up.left.and.arrow.down.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(5)
                    .background(CicadaTheme.shape(5).fill(CicadaTheme.bgFocus))
                    .padding(6)
                    .opacity(isHovered && image != nil ? 1 : 0)
            }
        }
        .buttonStyle(.cicadaPlain)
        .onHover { isHovered = $0 }
        .help(Copy.Links.enlarge)
        .task(id: "\(store?.bank ?? "")|\(path)") {
            image = nil
            guard let url = StoredPreviewPath.url(path) else { return }
            image = await PictureStore.shared.image(url, bank: store?.bank ?? "")
        }
        .sheet(isPresented: $showLightbox) {
            if let image { ImageLightbox(image: image, caption: caption) }
        }
    }
}

// MARK: - ImageLightbox
//
// A picture already loaded, large, with scroll-to-zoom, its caption (a capture keeps its date line) and an ✕. It
// loads nothing of its own.
struct ImageLightbox: View {
    let image: NSImage
    var caption: String? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var zoom: CGFloat = 1.0
    @State private var committedZoom: CGFloat = 1.0

    var body: some View {
        ZStack {
            Color.black.opacity(0.92)
                .onTapGesture { dismiss() }

            VStack(spacing: CicadaTheme.spacingSM) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .scaleEffect(zoom)
                    .gesture(
                        MagnificationGesture()
                            .onChanged { value in
                                // Accumulate against the last committed zoom so repeated pinches don't snap back.
                                zoom = max(1.0, min(5.0, committedZoom * value))
                            }
                            .onEnded { _ in committedZoom = zoom }
                    )
                if let caption {
                    Text(caption)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(.white.opacity(0.8))
                }
            }
            .padding(CicadaTheme.spacingXL)

            VStack {
                HStack {
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark")
                            .font(CicadaTheme.font(size: 14, weight: .semibold))
                            .foregroundStyle(.white)
                            .frame(width: 34, height: 34)
                            .background(.black.opacity(0.5))
                            .clipShape(Circle())
                    }
                    .buttonStyle(.cicadaPlain)
                    .help(Copy.Looks.closeHelp)
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }
        }
        .frame(minWidth: 600, minHeight: 440)
        .frame(width: 880, height: 640)
    }
}
