import AppKit
import Foundation

/// ROR-118 — the first frame of a picture. `LogoStore` and `PictureStore` are actors, so even a memory hit costs an
/// `await` and a hop: a page switch drew every avatar and logo as its fallback, then popped the image in a frame or
/// three later (measured at about 50-60 ms). This is the same memory as a lock-guarded mirror those actors fill and
/// forget with, readable synchronously from a view's `body`, so a picture already seen is drawn on the page's first
/// frame. It holds nothing the actors do not: a miss here still goes through them.
final class ImageMemory: @unchecked Sendable {
    static let logos = ImageMemory()
    static let pictures = ImageMemory()

    private let lock = NSLock()
    private var images: [String: NSImage] = [:]

    func image(_ key: String) -> NSImage? {
        lock.lock(); defer { lock.unlock() }
        return images[key]
    }

    func set(_ key: String, _ image: NSImage) {
        lock.lock(); defer { lock.unlock() }
        images[key] = image
    }

    func clear(prefix: String) {
        lock.lock(); defer { lock.unlock() }
        images = images.filter { !$0.key.hasPrefix(prefix) }
    }
}

extension LogoStore {
    /// The logo if it was already seen this run, on the first frame.
    nonisolated static func cachedImage(entityId: String, bank: String) -> NSImage? {
        ImageMemory.logos.image("\(bank)/\(entityId)")
    }
}

extension PictureStore {
    /// The picture if it was already seen this run, on the first frame.
    nonisolated static func cachedImage(_ url: PictureURL, bank: String) -> NSImage? {
        ImageMemory.pictures.image("\(bank)|\(url.cacheKey)")
    }
}

/// ROR-135 — the one synchronous question both the avatar and the graph's hover card ask: is this page's picture already
/// in memory, on the first frame? Nothing is read or fetched here.
enum PictureMemory {
    static func cached(id: String, picture: EntityPictureRef?, bank: String) -> NSImage? {
        guard let picture, let raw = picture.url else { return nil }
        switch picture.source {
        case .logo: return LogoStore.cachedImage(entityId: id, bank: bank)
        case .upload, .contacts, .messages, .thumbnail, .profile:
            return PictureURL.parse(raw).flatMap { PictureStore.cachedImage($0, bank: bank) }
        case .initials: return nil
        }
    }
}

/// ROR snappy — the first view of a picture is the second pop-in: `ImageMemory` only held what this run had already
/// drawn, so a page switch to Clusters drew grey initials, then the photo a frame or three later (seen at +30–40 ms in a
/// recorded page switch). After the graph lands, the pictures already on this Mac's disk are read into `ImageMemory` on a
/// utility-priority task (never the main thread, never the network), so the first frame of any page already has them.
enum PicturePrefetch {
    /// A bound on what one pass reads; the rest still load through the avatar's own `.task`.
    static let limit = 800

    static func run(_ pictures: [(id: String, picture: EntityPictureRef)], bank: String) {
        guard !pictures.isEmpty else { return }
        Task.detached(priority: .utility) {
            var read = 0
            for (id, picture) in pictures {
                if read >= limit || Task.isCancelled { break }
                guard let raw = picture.url else { continue }
                switch picture.source {
                case .logo: LogoStore.shared.warm(entityId: id, bank: bank)
                case .upload, .contacts, .messages, .thumbnail, .profile:
                    if let url = PictureURL.parse(raw) { PictureStore.shared.warm(url, bank: bank) }
                case .initials: continue
                }
                read += 1
            }
        }
    }
}
