import CoreGraphics
import Foundation

/// Aseprite json-array data: inclusive tag ranges, top-left rectangles, milliseconds and frame-keyed slices.
struct AsepriteSheetData: Decodable, Equatable {
    struct Rect: Decodable, Equatable {
        let x, y, w, h: Int
        var cgRect: CGRect { CGRect(x: x, y: y, width: w, height: h) }
    }
    struct Size: Decodable, Equatable { let w, h: Int }
    struct Frame: Decodable, Equatable {
        let frame: Rect
        let sourceSize: Size
        let frameMs: Int
        enum CodingKeys: String, CodingKey { case frame, sourceSize, frameMs = "duration" }
    }
    struct Tag: Decodable, Equatable {
        let name: String
        let from, to: Int
        let direction: String
    }
    struct SliceKey: Decodable, Equatable { let frame: Int; let bounds: Rect }
    struct Slice: Decodable, Equatable { let name: String; let keys: [SliceKey] }
    struct Meta: Decodable, Equatable {
        let image: String
        let size: Size
        let frameTags: [Tag]
        let slices: [Slice]
    }
    let frames: [Frame]
    let meta: Meta
}
