import AppKit
import SwiftUI

/// A saved item's picture as Cicada stores it: the backend fetched the page's own image (or YouTube's still, or a saved
/// PDF's first page) once and serves it at `/entities/{id}/preview?v=…`; the person's own upload is served the same
/// way. It is loaded with the bearer through `PictureStore` — the app never asks a provider for a thumbnail. Anything
/// that is not a path on Cicada's own API, a 404, or no path at all draws `placeholder`.
struct StoredPreview<Placeholder: View>: View {
    let path: String?
    @ViewBuilder var placeholder: () -> Placeholder

    /// Optional: a preview hosted outside the app's Store (a test, an offscreen render) still draws its placeholder.
    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    private var bank: String { store?.bank ?? "" }

    var body: some View {
        ZStack {
            if let image {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                placeholder()
            }
        }
        .task(id: "\(bank)|\(path ?? "-")") {
            image = nil
            guard let url = StoredPreviewPath.url(path) else { return }
            image = await PictureStore.shared.image(url, bank: bank)
        }
    }
}

/// What `StoredPreview` will load, pure: only a path on Cicada's own API — never an external URL.
enum StoredPreviewPath {
    static func url(_ path: String?) -> PictureURL? {
        guard let parsed = PictureURL.parse(path), case .api = parsed else { return nil }
        return parsed
    }

    static func loads(_ path: String?) -> Bool { url(path) != nil }
}
