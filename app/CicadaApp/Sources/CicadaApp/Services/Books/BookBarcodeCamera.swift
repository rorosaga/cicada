import AppKit
import AVFoundation
import SwiftUI
import Vision

/// ROR-116, G233 — "Scan with the camera" on the Book scans page: this Mac's camera (the built-in one, or an iPhone as a
/// Continuity Camera) shows its live feed in a window over the app, outlines the book and the code it sees, and takes a
/// book's number by itself (`BookScanStabilizer`) — no shutter — then keeps looking for the next.
///
/// Rails (capture, CLAUDE.md "Books"): the camera starts only on the person's click — macOS asks then, never before; a
/// frame is read in memory by Vision and dropped, never stored, never sent (only the ISBN it held leaves, through the
/// phone's own `POST /capture/isbn`); the session stops when the window closes, the app has been in the background for
/// a moment, or the view goes away. The preview layer reads the session, not the analysis, and the analysis drops late
/// frames instead of queueing them, so the feed never waits on Vision.
/// This is the one place the app opens a camera, so it is on `AVImportLintTests`' list.

/// A barcode's text as an ISBN-13, the same check the backend makes (`books.isbn13`): 13 digits starting 978 or 979 whose
/// last digit checks, or an ISBN-10 (converted). Anything else — a price code, a QR — is not a book.
enum BookISBN {
    static func parse(_ raw: String) -> String? {
        let text = raw.uppercased().filter { !"- ".contains($0) }.replacingOccurrences(of: "ISBN", with: "")
        if text.count == 10, let isbn = fromTen(text) { return isbn }
        guard text.count == 13, text.allSatisfy(\.isNumber), text.hasPrefix("978") || text.hasPrefix("979"),
              checkDigit(String(text.prefix(12))) == text.last else { return nil }
        return text
    }

    private static func checkDigit(_ body: String) -> Character {
        let total = body.enumerated().reduce(0) { $0 + (Int(String($1.element)) ?? 0) * ($1.offset % 2 == 0 ? 1 : 3) }
        return Character(String((10 - total % 10) % 10))
    }

    private static func fromTen(_ text: String) -> String? {
        let digits = Array(text)
        guard digits.prefix(9).allSatisfy(\.isNumber), digits[9].isNumber || digits[9] == "X" else { return nil }
        let total = digits.enumerated().reduce(0) { $0 + (10 - $1.offset) * ($1.element == "X" ? 10 : Int(String($1.element))!) }
        guard total % 11 == 0 else { return nil }
        let body = "978" + String(text.prefix(9))
        return body + String(checkDigit(body))
    }
}

enum BarcodeCameraState: Equatable {
    case off, starting, running
    /// macOS (or the person) said no: the one fix, in words, beside the button.
    case denied
    /// No camera on this Mac.
    case unavailable
}

@MainActor
@Observable
final class BookBarcodeCamera {
    private(set) var state: BarcodeCameraState = .off
    /// The feed is shown mirrored on this Mac's own camera, as FaceTime does: holding a book up to a laptop camera, the
    /// book then moves the way the hand does. A Continuity Camera or an external one is not mirrored — it points away
    /// from the person like a phone's. Set before the session starts; the highlight maps with the same flag.
    private(set) var mirrored = false
    @ObservationIgnored let session = AVCaptureSession()
    @ObservationIgnored private let queue = DispatchQueue(label: "cicada.book-camera", qos: .userInitiated)
    @ObservationIgnored private let analyzer = FrameAnalyzer()
    /// What the latest analysed frame held (about every 50 ms), for the highlight.
    @ObservationIgnored var onFrame: ((ScanFrame) -> Void)?
    /// A book's number taken, or a code that is not a book's. The camera keeps running.
    @ObservationIgnored var onEvent: ((ScanEvent) -> Void)?

    /// Open the camera (the person's click). The prompt, when macOS has not asked yet, is this call's.
    func start() async {
        guard state == .off || state == .denied || state == .unavailable else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: break
        case .notDetermined:
            state = .starting
            guard await AVCaptureDevice.requestAccess(for: .video) else { state = .denied; return }
            // The person may have left while macOS asked: stop() set this to off, and the camera stays closed.
            guard state == .starting else { return }
        default:
            state = .denied
            return
        }
        guard let device = Self.device() else { state = .unavailable; return }
        state = .starting
        mirrored = device.deviceType == .builtInWideAngleCamera
        analyzer.onFrame = { [weak self] frame in Task { @MainActor in self?.deliver(frame) } }
        analyzer.onEvent = { [weak self] event in Task { @MainActor in self?.deliver(event) } }
        let session = session, analyzer = analyzer
        queue.async { [weak self] in
            // The preview is up as soon as the session runs; configuring and starting never block the main thread.
            session.beginConfiguration()
            // 1280×720: a crisp feed in a large window, and enough pixels to read a barcode a hand's length away.
            session.sessionPreset = session.canSetSessionPreset(.hd1280x720) ? .hd1280x720 : .high
            session.inputs.forEach { session.removeInput($0) }
            session.outputs.forEach { session.removeOutput($0) }
            let out = AVCaptureVideoDataOutput()
            out.alwaysDiscardsLateVideoFrames = true   // drop, never queue: the analysis never makes the feed wait
            out.setSampleBufferDelegate(analyzer, queue: DispatchQueue(label: "cicada.book-camera.frames", qos: .userInitiated))
            guard let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input),
                  session.canAddOutput(out) else {
                session.commitConfiguration()
                Task { @MainActor in self?.state = .unavailable }
                return
            }
            session.addInput(input)
            session.addOutput(out)
            session.commitConfiguration()
            analyzer.reset()
            session.startRunning()
            Task { @MainActor in if self?.state == .starting { self?.state = .running } }
        }
    }

    /// Close it: the light goes out, no frame is held. Safe to call twice.
    func stop() {
        guard state != .off else { return }
        state = .off
        analyzer.onFrame = nil
        analyzer.onEvent = nil
        let session = session
        queue.async { if session.isRunning { session.stopRunning() } }
    }

    /// A number whose capture failed may be read again.
    func forget(_ isbn: String) { analyzer.forget(isbn) }

    private func deliver(_ frame: ScanFrame) { if state != .off { onFrame?(frame) } }
    private func deliver(_ event: ScanEvent) { if state != .off { onEvent?(event) } }

    /// The Mac's own camera first (fastest to open), else a Continuity Camera or any other.
    private static func device() -> AVCaptureDevice? {
        let found = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera, .continuityCamera, .external], mediaType: .video, position: .unspecified)
        return found.devices.first ?? AVCaptureDevice.default(for: .video)
    }
}

/// Reads frames with Vision, in memory, and drops each. About 20 a second at most; the book-shaped rectangle (the dearer
/// request) every third. Frames arrive on one serial queue; the lock covers `reset` / `forget` from the main actor.
private final class FrameAnalyzer: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    static let minInterval: TimeInterval = 1.0 / 20.0
    static let rectangleEvery = 3

    var onFrame: (@Sendable (ScanFrame) -> Void)?
    var onEvent: (@Sendable (ScanEvent) -> Void)?
    private let lock = NSLock()
    private var stabilizer = BookScanStabilizer()
    private var lastAt = -Double.infinity
    private var count = 0
    private var book: ScanQuad?

    func reset() {
        lock.lock(); stabilizer = BookScanStabilizer(); lastAt = -.infinity; count = 0; book = nil; lock.unlock()
    }

    func forget(_ isbn: String) { lock.lock(); stabilizer.forget(isbn); lock.unlock() }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let at = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
        guard let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lock.lock()
        let due = at - lastAt >= Self.minInterval
        if due { lastAt = at }
        lock.unlock()
        guard due else { return }
        let handler = VNImageRequestHandler(cvPixelBuffer: pixels, options: [:])
        let readings = BookFrameVision.barcodes(handler)
        lock.lock()
        if count % Self.rectangleEvery == 0 { book = BookFrameVision.bookRectangle(handler) }
        count += 1
        let event = stabilizer.feed(readings)
        let book = book
        lock.unlock()
        let primary = readings.first(where: { $0.isbn != nil }) ?? readings.first
        onFrame?(ScanFrame(imageSize: CGSize(width: CVPixelBufferGetWidth(pixels), height: CVPixelBufferGetHeight(pixels)),
                           barcode: primary?.quad, barcodeIsBook: primary?.isbn != nil, book: book))
        if let event { onEvent?(event) }
    }
}

/// The live feed, aspect-fill, mirrored as the camera says (the highlight maps with the same flag).
struct BookCameraPreview: NSViewRepresentable {
    let session: AVCaptureSession
    let mirrored: Bool

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.wantsLayer = true
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer = layer
        apply(layer)
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        if let layer = nsView.layer as? AVCaptureVideoPreviewLayer { apply(layer) }
    }

    private func apply(_ layer: AVCaptureVideoPreviewLayer) {
        guard let connection = layer.connection, connection.isVideoMirroringSupported else { return }
        connection.automaticallyAdjustsVideoMirroring = false
        connection.isVideoMirrored = mirrored
    }
}
