import CoreGraphics
import Foundation
import Vision

/// G233 — what Vision is asked of one frame, in memory. Kept apart from the camera (which owns AVFoundation) so a drawn
/// image can run through the same two requests in a test.
enum BookFrameVision {
    /// The codes a book, a shelf label or a receipt can carry. EAN-13 is a book's; the rest are read only so the scanner
    /// can say "that is not a book's number" instead of staring silently at it.
    static let symbologies: [VNBarcodeSymbology] = [.ean13, .ean8, .upce, .code128, .qr]

    static func barcodes(_ handler: VNImageRequestHandler) -> [BarcodeReading] {
        let request = VNDetectBarcodesRequest()
        request.symbologies = symbologies
        try? handler.perform([request])
        return (request.results ?? []).compactMap { observation in
            guard let payload = observation.payloadStringValue else { return nil }
            return BarcodeReading(payload: payload, quad: ScanQuad(observation))
        }
    }

    /// The most book-shaped rectangle in view: a portrait or landscape cover (short side over long side 0.5…0.9, the
    /// range from a squat paperback to an A4 sheet), at least a quarter of the frame's short side so the white label
    /// around a barcode is not mistaken for the book.
    static func bookRectangle(_ handler: VNImageRequestHandler) -> ScanQuad? {
        let request = VNDetectRectanglesRequest()
        request.minimumAspectRatio = 0.5
        request.maximumAspectRatio = 0.9
        request.minimumSize = 0.25
        request.minimumConfidence = 0.6
        request.quadratureTolerance = 25
        request.maximumObservations = 1
        try? handler.perform([request])
        return request.results?.first.map(ScanQuad.init)
    }
}

extension ScanQuad {
    init(_ observation: VNRectangleObservation) {
        self.init(topLeft: observation.topLeft, topRight: observation.topRight,
                  bottomRight: observation.bottomRight, bottomLeft: observation.bottomLeft)
    }
}
