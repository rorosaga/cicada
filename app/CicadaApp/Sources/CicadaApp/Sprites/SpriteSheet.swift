import Foundation
import CoreGraphics
import ImageIO
import OSLog

/// One decoded sheet. Identical packed rectangles share a crop and backing storage.
final class SpriteSheet {
    let name: String
    let image: CGImage
    let frameRects: [CGRect]
    let rectIndex: [Int]
    let frameSeconds: [TimeInterval]
    let frameSize: CGSize
    let tags: [String: SpriteClip]
    let slices: [String: CGRect]
    private let lock = NSLock()
    private var crops: [Int: CGImage] = [:]

    init?(name: String, data: AsepriteSheetData, image: CGImage) {
        guard let first = data.frames.first, first.sourceSize.w > 0, first.sourceSize.h > 0,
              image.width == data.meta.size.w, image.height == data.meta.size.h,
              data.frames.allSatisfy({ f in
                  f.sourceSize == first.sourceSize && f.frame.w == first.sourceSize.w
                      && f.frame.h == first.sourceSize.h && f.frame.x >= 0 && f.frame.y >= 0
                      && f.frame.x <= image.width - f.frame.w && f.frame.y <= image.height - f.frame.h
                      && f.frameMs > 0
              }),
              Set(data.meta.frameTags.map(\.name)).count == data.meta.frameTags.count,
              data.meta.frameTags.allSatisfy({ $0.from >= 0 && $0.to >= $0.from && $0.to < data.frames.count
                  && ["forward", "reverse", "pingpong", "pingpong_reverse"].contains($0.direction) }),
              Set(data.meta.slices.map(\.name)).count == data.meta.slices.count else { return nil }
        self.name = name
        self.image = image
        frameSize = CGSize(width: first.sourceSize.w, height: first.sourceSize.h)
        frameRects = data.frames.map { $0.frame.cgRect }
        let seconds = data.frames.map { Double($0.frameMs) / 1000 }
        frameSeconds = seconds
        var distinct: [CGRect] = []
        rectIndex = frameRects.map { rect in
            if let i = distinct.firstIndex(of: rect) { return i }
            distinct.append(rect)
            return distinct.count - 1
        }
        var clips: [String: SpriteClip] = [:]
        for t in data.meta.frameTags {
            var order = Array(t.from...t.to)
            if t.direction == "reverse" || t.direction == "pingpong_reverse" { order.reverse() }
            if (t.direction == "pingpong" || t.direction == "pingpong_reverse"), order.count > 2 {
                order += order.dropFirst().dropLast().reversed()
            }
            clips[t.name] = SpriteClip(sheet: name, tag: t.name, order: order, seconds: order.map { seconds[$0] })
        }
        tags = clips
        var bounds: [String: CGRect] = [:]
        let canvas = CGRect(origin: .zero, size: frameSize)
        for s in data.meta.slices {
            if let key = s.keys.first(where: { $0.frame == 0 }) {
                guard key.bounds.w > 0, key.bounds.h > 0, canvas.contains(key.bounds.cgRect) else { return nil }
                bounds[s.name] = key.bounds.cgRect
            }
        }
        slices = bounds
    }

    func frameImage(_ index: Int) -> CGImage? {
        guard frameRects.indices.contains(index) else { return nil }
        lock.lock()
        defer { lock.unlock() }
        let key = rectIndex[index]
        if let hit = crops[key] { return hit }
        let crop = image.cropping(to: frameRects[index])
        crops[key] = crop
        return crop
    }

    func clip(_ tag: String) -> SpriteClip? { tags[tag] }
}

enum SpriteSheets {
    private enum Entry { case loaded(SpriteSheet), missing }
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: Entry] = [:]
    private static let logger = Logger(subsystem: "com.cicada.app", category: "sprites")

    /// Both bundle layouts use the bare sprites directory. Failures are cached per bundle and name.
    static func sheet(named name: String, in bundle: Bundle = .cicadaResources) -> SpriteSheet? {
        lock.lock()
        defer { lock.unlock() }
        let key = bundle.bundleURL.path + "|" + name
        if let entry = cache[key] {
            if case .loaded(let sheet) = entry { return sheet }
            return nil
        }
        guard let json = bundle.cicadaResource(name, ext: "json", in: "sprites"),
              let png = bundle.cicadaResource(name, ext: "png", in: "sprites"),
              let bytes = try? Data(contentsOf: json),
              let data = try? JSONDecoder().decode(AsepriteSheetData.self, from: bytes),
              let source = CGImageSourceCreateWithURL(png as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCache: true] as CFDictionary),
              let sheet = SpriteSheet(name: name, data: data, image: image) else {
            cache[key] = .missing
            logger.error("Sprite sheet unavailable: \(name, privacy: .public)")
            return nil
        }
        cache[key] = .loaded(sheet)
        return sheet
    }
}
