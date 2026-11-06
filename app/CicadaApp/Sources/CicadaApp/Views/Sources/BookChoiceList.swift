import ImageIO
import SwiftUI

/// G233 — several books could go into memory: the person confirms all or picks some, and nothing enters before that.
/// Everything starts ticked (confirm all is one click). DR-5 (one primary: the add), DR-38 (said once), DR-59 (one line a
/// book), DR-9 (a ring, not a border).
struct BookChoiceItem: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String
    /// Where its cover comes from, if anywhere: no cover, no picture (never a stand-in).
    var cover: BookChoiceCover.Source? = nil
}

/// G233 — a book's cover thumbnail in the choice list, loading in as it arrives. Apple Books' comes from its own cache on
/// this Mac (read here, nothing leaves); a Goodreads row's from the backend by the export's ISBN (the existing lookup,
/// behind its gate, one request a second, cached outside every bank). A book with none leaves the space empty.
struct BookChoiceCover: View {
    enum Source: Hashable, Sendable {
        case file(URL)
        case isbn(String)
    }

    static let size = CGSize(width: 24, height: 36)
    let source: Source?
    @State private var image: NSImage?

    var body: some View {
        ZStack {
            if let image {
                Image(nsImage: image).resizable().scaledToFill()
                    .frame(width: Self.size.width, height: Self.size.height).clipped()
                    .clipShape(CicadaTheme.shape(CicadaTheme.radiusXS))
                    .overlay(CicadaTheme.shape(CicadaTheme.radiusXS)
                        .strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
            }
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .task(id: source) { image = await BookChoiceCovers.shared.image(for: source) }
        .accessibilityHidden(true)
    }
}

/// The loads behind `BookChoiceCover`: remembered in memory (this list is not a Store domain), one backend ask at a
/// time so the list never queues more than the one-a-second lookup behind it can answer.
actor BookChoiceCovers {
    static let shared = BookChoiceCovers()
    private var cache: [BookChoiceCover.Source: NSImage?] = [:]
    private var tail: Task<Void, Never>?

    func image(for source: BookChoiceCover.Source?) async -> NSImage? {
        guard let source else { return nil }
        if let hit = cache[source] { return hit }
        let image: NSImage?
        switch source {
        case .file(let url):
            image = await Task.detached(priority: .utility) { Self.thumbnail(url) }.value
        case .isbn(let isbn):
            image = await queued { await Self.fetch(isbn) }
        }
        cache[source] = .some(image)
        return image
    }

    private func queued(_ work: @escaping @Sendable () async -> NSImage?) async -> NSImage? {
        let previous = tail
        let job = Task<NSImage?, Never> { await previous?.value; return await work() }
        tail = Task { _ = await job.value }
        return await job.value
    }

    nonisolated static func fetch(_ isbn: String) async -> NSImage? {
        guard let data = try? await APIClient.shared.fetchChoiceCover(isbn: isbn) else { return nil }
        return NSImage(data: data)
    }

    /// A small picture drawn down from the file Apple Books keeps, twice the row's size for a sharp retina edge.
    nonisolated static func thumbnail(_ file: URL) -> NSImage? {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceThumbnailMaxPixelSize: 96,
              ] as CFDictionary) else { return nil }
        return NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
    }
}

struct BookChoiceList: View {
    let items: [BookChoiceItem]
    var busy = false
    /// Nil hides it: a source that can ask again (a file) has no "leave out".
    var onLeaveOut: ((Set<String>) -> Void)? = nil
    let onAdd: (Set<String>) -> Void

    @State private var ticked: Set<String> = []
    @State private var seeded = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                PrimaryActionButton(title: Copy.booksAddChosen(ticked.count, of: items.count)) { onAdd(ticked) }
                    .disabled(busy || ticked.isEmpty).fixedSize()
                TextButton(title: ticked.count == items.count ? Copy.booksSelectNone : Copy.booksSelectAll) {
                    ticked = ticked.count == items.count ? [] : Set(items.map(\.id))
                }
                if let onLeaveOut {
                    TextButton(title: Copy.booksLeaveOut) { onLeaveOut(ticked) }.disabled(busy)
                }
                Spacer(minLength: 0)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(items) { item in
                        Toggle(isOn: Binding(get: { ticked.contains(item.id) },
                                             set: { on in if on { ticked.insert(item.id) } else { ticked.remove(item.id) } })) {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                BookChoiceCover(source: item.cover)
                                Text(item.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                                    .lineLimit(1)
                                if !item.author.isEmpty {
                                    Text(item.author).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .toggleStyle(.checkbox)
                        .frame(height: CicadaTheme.scaled(44), alignment: .leading)
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(260))
        }
        .onAppear { if !seeded { ticked = Set(items.map(\.id)); seeded = true } }
        .onChange(of: items) { _, new in ticked = ticked.intersection(Set(new.map(\.id))).union(
            Set(new.map(\.id)).subtracting(Set(items.map(\.id)))) }
    }
}
