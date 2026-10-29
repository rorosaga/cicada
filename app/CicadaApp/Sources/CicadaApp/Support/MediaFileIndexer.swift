import AVFoundation
import CoreGraphics
import CryptoKit
import Foundation
import ImageIO
import Speech
import UniformTypeIdentifiers

/// Meaning index 2 (owner via the coordinator, 2026-10-28: "go with the recommendation") — a recording or a video the
/// person picks or drops becomes searchable by meaning. **The app reads, the backend parses bytes** (G195): this
/// file is the only place the recording is opened. It
///
/// * transcribes the speech **on this Mac** with Apple's own recogniser (`SpeechAnalyzer` + `SpeechTranscriber`,
///   macOS 26+) — no model of Cicada's, nothing downloaded: when macOS has no speech model for the language, the file
///   is kept without words and the toast says how to add one (Dictation's own setting), never a download of ours;
/// * for a video, samples a frame every `MediaFrames.every` seconds (at most `MediaFrames.maxSamples`) and keeps one
///   per shot — an 8 × 8 average hash that moved more than `MediaFrames.minBits` bits from the last kept frame — each
///   a ≤ 640 × 400 JPEG with its time;
/// * posts only those derivatives (`POST /files/media`, `POST /files/<id>/frames`): never the path, never the bytes.
///
/// **Speech permission (checked with fixtures only, never raised on a developer's Mac).** `SFSpeechRecognizer`'s
/// header documents a Speech Recognition prompt (`requestAuthorization`, `NSSpeechRecognitionUsageDescription`);
/// `SpeechAnalyzer`'s Swift interface declares no authorization API of its own, and whether it is gated by the same
/// TCC service could not be shown without raising one. So the app treats it as gated: `authorizationStatus()` is
/// read (it never prompts), the request is made only inside `add(_:)` — the person's own drop or pick — and a denial
/// keeps the file without words, said in words. Nothing on launch, a timer or a background task ever asks.
///
/// **Whose words.** A transcript is the recording's words: whoever spoke is unknown to Cicada, so they are never the
/// person's own (the backend stores them as `words_by: the recording`, never an episode, never read by Sleep).
enum MediaKind: String, Equatable {
    case audio, video

    /// Audio or video by the file's type (its extension's UTType) — `nil` for anything else.
    static func of(_ url: URL) -> MediaKind? {
        guard let type = UTType(filenameExtension: url.pathExtension.lowercased()) else { return nil }
        if type.conforms(to: .movie) || type.conforms(to: .video) { return .video }
        if type.conforms(to: .audio) { return .audio }
        return nil
    }
}

struct TranscriptSegment: Equatable {
    var start: Double
    var end: Double
    var text: String
}

enum SpeechAccess: Equatable { case authorized, notDetermined, denied, unavailable }

/// The permission seam: `status` never prompts; `request()` may, and is called only from `add(_:)`.
protocol SpeechAuthorizing: Sendable {
    func status() -> SpeechAccess
    func request() async -> SpeechAccess
}

struct SystemSpeechAuthorizer: SpeechAuthorizing {
    func status() -> SpeechAccess { Self.map(SFSpeechRecognizer.authorizationStatus()) }

    func request() async -> SpeechAccess {
        await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { cont.resume(returning: Self.map($0)) }
        }
    }

    static func map(_ s: SFSpeechRecognizerAuthorizationStatus) -> SpeechAccess {
        switch s {
        case .authorized: return .authorized
        case .notDetermined: return .notDetermined
        case .denied, .restricted: return .denied
        @unknown default: return .unavailable
        }
    }
}

enum TranscribeOutcome: Equatable {
    case words([TranscriptSegment])
    case noSpeechModel          // macOS has no on-device model for the language; we never download one
    case unsupported            // before macOS 26, or a file with no readable audio track
}

protocol Transcribing: Sendable {
    func transcribe(_ url: URL, locale: Locale) async -> TranscribeOutcome
}

struct SystemTranscriber: Transcribing {
    func transcribe(_ url: URL, locale: Locale) async -> TranscribeOutcome {
        guard #available(macOS 26.0, *) else { return .unsupported }
        return await Self.run(url, locale: locale)
    }

    @available(macOS 26.0, *)
    static func run(_ url: URL, locale: Locale) async -> TranscribeOutcome {
        guard SpeechTranscriber.isAvailable,
              let matched = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else { return .unsupported }
        let installed = await SpeechTranscriber.installedLocales
        guard installed.contains(where: { $0.identifier(.bcp47) == matched.identifier(.bcp47) }) else {
            return .noSpeechModel
        }
        let transcriber = SpeechTranscriber(locale: matched, transcriptionOptions: [], reportingOptions: [],
                                            attributeOptions: [.audioTimeRange])
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        guard let file = try? AVAudioFile(forReading: url) else { return .unsupported }
        do {
            async let collected: [TranscriptSegment] = {
                var out: [TranscriptSegment] = []
                for try await result in transcriber.results {
                    let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !text.isEmpty else { continue }
                    let start = result.range.start.seconds, dur = result.range.duration.seconds
                    out.append(TranscriptSegment(start: start.isFinite ? start : 0,
                                                 end: (start + dur).isFinite ? start + dur : 0, text: text))
                }
                return out
            }()
            try await analyzer.start(inputAudioFile: file, finishAfterFile: true)
            return .words(try await collected)
        } catch {
            return .unsupported
        }
    }
}

// MARK: - Frames

enum MediaFrames {
    static let every: Double = 3
    static let maxSamples = 1200
    static let minBits = 4
    static let maxWidth = 640, maxHeight = 400

    /// The 8 × 8 average hash: each bit says whether that cell is brighter than the picture's mean.
    static func averageHash(_ image: CGImage) -> UInt64 {
        let side = 8
        var pixels = [UInt8](repeating: 0, count: side * side)
        let space = CGColorSpaceCreateDeviceGray()
        pixels.withUnsafeMutableBytes { buf in
            guard let ctx = CGContext(data: buf.baseAddress, width: side, height: side, bitsPerComponent: 8,
                                      bytesPerRow: side, space: space,
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return }
            ctx.interpolationQuality = .medium
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: side, height: side))
        }
        let mean = pixels.reduce(0) { $0 + Int($1) } / pixels.count
        var hash: UInt64 = 0
        for (i, p) in pixels.enumerated() where Int(p) > mean { hash |= 1 << UInt64(i) }
        return hash
    }

    static func distance(_ a: UInt64, _ b: UInt64) -> Int { (a ^ b).nonzeroBitCount }

    /// Which sampled frames to keep: the first, then each whose hash moved more than `minBits` from the last kept.
    static func keep(_ hashes: [UInt64]) -> [Int] {
        var kept: [Int] = []
        var last: UInt64?
        for (i, h) in hashes.enumerated() {
            if let l = last, distance(l, h) <= minBits { continue }
            kept.append(i)
            last = h
        }
        return kept
    }

    /// The times to sample in a video of `length` seconds: every `every` seconds, at most `maxSamples`.
    static func times(seconds length: Double) -> [Double] {
        guard length.isFinite, length > 0 else { return [0] }
        let n = min(maxSamples, Int(length / every) + 1)
        return (0..<n).map { Double($0) * every }
    }

    /// A ≤ 640 × 400 JPEG of `image` (aspect kept), ≤ 200 KB: lower quality until it fits.
    static func jpeg(_ image: CGImage) -> Data? {
        let scale = min(1, Double(maxWidth) / Double(image.width), Double(maxHeight) / Double(image.height))
        let w = max(1, Int(Double(image.width) * scale)), h = max(1, Int(Double(image.height) * scale))
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.interpolationQuality = .high
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        guard let small = ctx.makeImage() else { return nil }
        for quality in [0.75, 0.6, 0.45] {
            let data = NSMutableData()
            guard let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil)
            else { return nil }
            CGImageDestinationAddImage(dest, small, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
            guard CGImageDestinationFinalize(dest) else { return nil }
            if data.length <= 200 * 1024 { return data as Data }
        }
        return nil
    }
}

struct KeptFrame: Equatable {
    var t: Double
    var jpeg: Data
}

protocol FrameSampling: Sendable {
    func frames(_ url: URL) async -> (length: Double?, frames: [KeptFrame])
}

struct SystemFrameSampler: FrameSampling {
    func frames(_ url: URL) async -> (length: Double?, frames: [KeptFrame]) {
        let asset = AVURLAsset(url: url)
        let duration = (try? await asset.load(.duration)).map { CMTimeGetSeconds($0) }
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: MediaFrames.maxWidth * 2, height: MediaFrames.maxHeight * 2)
        let tolerance = CMTime(seconds: 0.5, preferredTimescale: 600)
        generator.requestedTimeToleranceBefore = tolerance
        generator.requestedTimeToleranceAfter = tolerance
        var sampled: [(Double, CGImage)] = []
        for t in MediaFrames.times(seconds: duration ?? 0) {
            guard let (image, _) = try? await generator.image(at: CMTime(seconds: t, preferredTimescale: 600))
            else { continue }
            sampled.append((t, image))
        }
        let kept = MediaFrames.keep(sampled.map { MediaFrames.averageHash($0.1) })
        let frames = kept.compactMap { i -> KeptFrame? in
            MediaFrames.jpeg(sampled[i].1).map { KeptFrame(t: sampled[i].0, jpeg: $0) }
        }
        return (duration, frames)
    }
}

// MARK: - The backend

protocol MediaFilesAPI: Sendable {
    func postMediaFile(_ body: [String: Any]) async throws -> String
    func postMediaFrames(fileId: String, frames: [KeptFrame]) async throws
}

extension APIClient: MediaFilesAPI {
    func postMediaFile(_ body: [String: Any]) async throws -> String {
        let out: [String: String] = try await postVideo("/files/media", body: body)
        return out["id"] ?? ""
    }

    func postMediaFrames(fileId: String, frames: [KeptFrame]) async throws {
        for start in stride(from: 0, to: frames.count, by: 64) {
            let batch = frames[start..<min(frames.count, start + 64)].map {
                ["t": $0.t, "jpeg": $0.jpeg.base64EncodedString()] as [String: Any]
            }
            let _: [String: Int] = try await postVideo("/files/\(fileId)/frames", body: ["frames": batch])
        }
    }
}

// MARK: - Where an added file is

/// Where this Mac last saw each added file (`file id → path`), so a palette hit can open it. Per-viewer state of
/// the app's own (UserDefaults), never posted: the backend never learns a path (G195). A file moved or deleted since
/// is simply not there — the hit says so and the person can add it again.
struct MediaFilePlaces {
    static let key = "cicada.mediaFiles.places"
    var defaults: UserDefaults = .standard

    func remember(_ id: String, _ url: URL) {
        guard !id.isEmpty else { return }
        var all = defaults.dictionary(forKey: Self.key) as? [String: String] ?? [:]
        all[id] = url.path
        defaults.set(all, forKey: Self.key)
    }

    /// The file's URL when it is still where it was added, else nil.
    func url(of id: String) -> URL? {
        guard let path = (defaults.dictionary(forKey: Self.key) as? [String: String])?[id],
              FileManager.default.fileExists(atPath: path) else { return nil }
        return URL(fileURLWithPath: path)
    }
}

// MARK: - The indexer

@MainActor
final class MediaFileIndexer {
    static let shared = MediaFileIndexer()

    private let api: any MediaFilesAPI
    private let speech: any SpeechAuthorizing
    private let transcriber: any Transcribing
    private let sampler: any FrameSampling
    private let locale: Locale
    let places: MediaFilePlaces
    /// What the person reads (the Store's toast); one sentence per drop, never a new visual pattern.
    var say: (String) -> Void = { _ in }

    init(api: any MediaFilesAPI = APIClient.shared, speech: any SpeechAuthorizing = SystemSpeechAuthorizer(),
         transcriber: any Transcribing = SystemTranscriber(), sampler: any FrameSampling = SystemFrameSampler(),
         locale: Locale = .current, places: MediaFilePlaces = MediaFilePlaces()) {
        self.api = api
        self.speech = speech
        self.transcriber = transcriber
        self.sampler = sampler
        self.locale = locale
        self.places = places
    }

    /// The audio and video among `urls` (files only; a folder's media is not walked here).
    nonisolated static func media(in urls: [URL]) -> [URL] {
        urls.filter { !$0.hasDirectoryPath && MediaKind.of($0) != nil }
    }

    /// The person's drop or pick: transcribe and sample each file on this Mac, post the derivatives. The only place
    /// Speech Recognition may be asked for (the person's own act). Returns when every file is posted.
    @discardableResult
    func add(_ urls: [URL]) async -> [AddOutcome] {
        let files = Self.media(in: urls)
        guard !files.isEmpty else { return [] }
        say(Copy.mediaAdding(files.count))
        var access = speech.status()
        if access == .notDetermined { access = await speech.request() }
        var outcomes: [AddOutcome] = []
        for url in files {
            outcomes.append(await addOne(url, speechAllowed: access == .authorized))
        }
        say(Copy.mediaAdded(outcomes))
        return outcomes
    }

    enum AddOutcome: Equatable { case added(words: Int, frames: Int), noWords(reason: String), failed }

    private func addOne(_ url: URL, speechAllowed: Bool) async -> AddOutcome {
        guard let kind = MediaKind.of(url), let sha = Self.sha256(of: url) else { return .failed }
        var segments: [TranscriptSegment] = []
        var reason: String?
        if speechAllowed {
            switch await transcriber.transcribe(url, locale: locale) {
            case .words(let segs): segments = segs
            case .noSpeechModel: reason = Copy.mediaNoSpeechModel
            case .unsupported: reason = Copy.mediaNoWords
            }
        } else {
            reason = Copy.mediaSpeechDenied
        }
        var sampled: (length: Double?, frames: [KeptFrame]) = (nil, [])
        if kind == .video { sampled = await sampler.frames(url) }
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        var body: [String: Any] = [
            "name": url.lastPathComponent, "kind": kind.rawValue, "sha256": sha, "size": size,
            "language": locale.identifier(.bcp47),
            "segments": segments.map { ["start": $0.start, "end": $0.end, "text": $0.text] },
        ]
        if let d = sampled.length ?? segments.last?.end { body["durationS"] = d }
        do {
            let id = try await api.postMediaFile(body)
            if !sampled.frames.isEmpty { try await api.postMediaFrames(fileId: id, frames: sampled.frames) }
            places.remember(id, url)
        } catch {
            return .failed
        }
        if segments.isEmpty, let reason { return kind == .video && !sampled.frames.isEmpty
            ? .added(words: 0, frames: sampled.frames.count) : .noWords(reason: reason) }
        return .added(words: segments.count, frames: sampled.frames.count)
    }

    /// The file's sha256, streamed in 1 MB reads (a long recording never sits in memory whole).
    nonisolated static func sha256(of url: URL) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try? handle.read(upToCount: 1 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
