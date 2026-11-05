import CoreGraphics
import Vision

/// ROR-117 / G43 — the words visible in a picture, read **on this Mac** with Apple's own text recogniser
/// (`VNRecognizeTextRequest`, on-device: nothing is sent anywhere to read it). A kept frame of an added video and, when
/// that door exists, a photo item both call `PictureText.reader.read(_:)`; the text is posted beside the picture as a
/// derivative (`POST /files/<id>/frames`, the frame's `text`), where the backend scrubs it like a transcript and keeps it
/// as text read from the picture — the picture's words, never the person's, never read by Sleep.
///
/// The recogniser needs no permission and no download. It reads only an image the app already holds in memory.
protocol PictureTextReading: Sendable {
    func read(_ image: CGImage) -> String
}

struct SystemPictureTextReader: PictureTextReading {
    func read(_ image: CGImage) -> String {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.automaticallyDetectsLanguage = true
        do { try VNImageRequestHandler(cgImage: image).perform([request]) } catch { return "" }
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        return PictureText.tidy(lines)
    }
}

enum PictureText {
    /// What one picture may carry (the backend keeps the same bound).
    static let maxChars = 4_000
    /// At most this many of a video's kept frames are read: it bounds the time a long recording takes to add, nothing else.
    static let maxPerFile = 600

    /// The recogniser's lines as one run of words: trimmed, empty lines gone, a repeated line kept once, in reading order.
    static func tidy(_ lines: [String]) -> String {
        var seen = Set<String>()
        var kept: [String] = []
        for line in lines {
            let text = line.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            if text.isEmpty || !seen.insert(text).inserted { continue }
            kept.append(text)
        }
        return String(kept.joined(separator: " ").prefix(maxChars))
    }
}
