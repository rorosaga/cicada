import CryptoKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// C11 (G146 plan R-PE2) — a picture the person chose, made small on this Mac before it leaves: at most 512 px on its
/// longer side, the camera's orientation applied, JPEG at 0.85 when opaque and PNG when it has alpha (JPEG if that PNG
/// would pass 512 KB). The server never resizes — Pillow is not a dependency — so this is the only shrink there is.
struct PreparedPicture: Equatable, Sendable {
    let data: Data
    let ext: String
    let width: Int
    let height: Int

    /// sha256[:12] of the bytes — `entity_picture.sha12`, so the upload's URL is known before the server answers (R-PE10).
    var sha: String {
        String(SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined().prefix(12))
    }
}

enum PictureImport {
    static let maxPixels = 512
    static let maxBytes = 512 * 1024
    static let minSide = 16
    static let jpegQuality = 0.85
    /// A photo straight off a phone is a few MB; past this it is not a picture someone meant to pick.
    static let maxInputBytes = 64 * 1024 * 1024

    enum Failure: Error, Equatable { case unreadable, tooSmall, tooLarge }

    static func isImage(_ url: URL) -> Bool {
        UTType(filenameExtension: url.pathExtension)?.conforms(to: .image) ?? false
    }

    static func prepare(fileURL: URL) throws -> PreparedPicture {
        let size = (try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        guard size <= maxInputBytes, let data = try? Data(contentsOf: fileURL) else { throw Failure.unreadable }
        return try prepare(data: data)
    }

    static func prepare(data: Data) throws -> PreparedPicture {
        guard data.count <= maxInputBytes,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetCount(source) > 0,
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceThumbnailMaxPixelSize: maxPixels,
                  kCGImageSourceShouldCacheImmediately: true,
              ] as CFDictionary)
        else { throw Failure.unreadable }
        guard min(image.width, image.height) >= minSide else { throw Failure.tooSmall }
        let opaque = [CGImageAlphaInfo.none, .noneSkipFirst, .noneSkipLast].contains(image.alphaInfo)
        var ext = opaque ? "jpg" : "png"
        var bytes = try encode(image, as: opaque ? .jpeg : .png)
        if bytes.count > maxBytes, !opaque {
            bytes = try encode(image, as: .jpeg)
            ext = "jpg"
        }
        guard bytes.count <= maxBytes else { throw Failure.tooLarge }
        return PreparedPicture(data: bytes, ext: ext, width: image.width, height: image.height)
    }

    private static func encode(_ image: CGImage, as type: UTType) throws -> Data {
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, type.identifier as CFString, 1, nil) else {
            throw Failure.unreadable
        }
        let options: [CFString: Any] = type == .jpeg ? [kCGImageDestinationLossyCompressionQuality: jpegQuality] : [:]
        CGImageDestinationAddImage(dest, image, options as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { throw Failure.unreadable }
        return out as Data
    }
}
