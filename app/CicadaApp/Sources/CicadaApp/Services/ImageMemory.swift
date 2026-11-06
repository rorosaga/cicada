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
