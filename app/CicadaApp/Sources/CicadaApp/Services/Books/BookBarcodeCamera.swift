import AppKit
import AVFoundation
import SwiftUI
import Vision

/// ROR-116, G233 — "Scan with the camera" on the Book scans page: this Mac's camera (the built-in one, or an iPhone as a
/// Continuity Camera) shows its live feed, and the first barcode that is a book's is taken with no shutter.
///
/// Rails (capture, CLAUDE.md "Books"): the camera starts only on the person's click — macOS asks then, never before; a
/// frame is read in memory by Vision and dropped, never stored, never sent (only the ISBN it held leaves, through the
/// phone's own `POST /capture/isbn`); the session stops the moment a code is read, the person stops it, or the view closes.
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
    @ObservationIgnored let session = AVCaptureSession()
    @ObservationIgnored private let queue = DispatchQueue(label: "cicada.book-camera", qos: .userInitiated)
    @ObservationIgnored private let reader = FrameReader()
    /// The first ISBN read; the camera has already been told to stop.
    @ObservationIgnored var onISBN: ((String) -> Void)?

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
        reader.onISBN = { [weak self] isbn in
            Task { @MainActor in
                guard let self, self.state != .off else { return }
                self.stop()
                self.onISBN?(isbn)
            }
        }
        let session = session, reader = reader
        queue.async { [weak self] in
            // The preview is up as soon as the session runs; configuring and starting never block the main thread.
            session.beginConfiguration()
            session.sessionPreset = .medium
            session.inputs.forEach { session.removeInput($0) }
            session.outputs.forEach { session.removeOutput($0) }
            let out = AVCaptureVideoDataOutput()
            out.alwaysDiscardsLateVideoFrames = true
            out.setSampleBufferDelegate(reader, queue: DispatchQueue(label: "cicada.book-camera.frames"))
            guard let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input),
                  session.canAddOutput(out) else {
                session.commitConfiguration()
                Task { @MainActor in self?.state = .unavailable }
                return
            }
            session.addInput(input)
            session.addOutput(out)
            session.commitConfiguration()
            reader.reset()
            session.startRunning()
            Task { @MainActor in if self?.state == .starting { self?.state = .running } }
        }
    }

    /// Close it: the light goes out, no frame is held. Safe to call twice.
    func stop() {
        guard state != .off else { return }
        state = .off
        let session = session
        queue.async { if session.isRunning { session.stopRunning() } }
    }

    /// The Mac's own camera first (fastest to open), else a Continuity Camera or any other.
    private static func device() -> AVCaptureDevice? {
        let found = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera, .continuityCamera, .external], mediaType: .video, position: .unspecified)
        return found.devices.first ?? AVCaptureDevice.default(for: .video)
    }
}

/// Reads each frame with Vision, in memory, and drops it. Only an EAN-13 (a book's barcode) that is a valid ISBN counts.
private final class FrameReader: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    var onISBN: ((String) -> Void)?
    private let lock = NSLock()
    private var done = false

    func reset() { lock.lock(); done = false; lock.unlock() }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        lock.lock(); let finished = done; lock.unlock()
        guard !finished, let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let request = VNDetectBarcodesRequest()
        request.symbologies = [.ean13]
        try? VNImageRequestHandler(cvPixelBuffer: pixels, options: [:]).perform([request])
        guard let isbn = request.results?.compactMap({ $0.payloadStringValue }).compactMap(BookISBN.parse).first else { return }
        lock.lock(); done = true; lock.unlock()
        onISBN?(isbn)
    }
}

/// The live feed.
struct BookCameraPreview: NSViewRepresentable {
    let session: AVCaptureSession

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.wantsLayer = true
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer = layer
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
