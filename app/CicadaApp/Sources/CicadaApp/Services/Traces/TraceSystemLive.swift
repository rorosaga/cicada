import AppKit
import ApplicationServices
import Carbon.HIToolbox
import CoreGraphics
import CoreServices
import Foundation
import ImageIO
import LocalAuthentication
import ScreenCaptureKit
import UniformTypeIdentifiers
import Vision

/// G218 — the live seams. Each is the only place its framework is called, and none ever calls a prompting API:
/// Accessibility by `AXIsProcessTrusted()`, Screen Recording by `CGPreflightScreenCaptureAccess()` (ScreenCaptureKit is
/// touched only after it says yes), Automation by `AEDeterminePermissionToAutomateTarget(askUserIfNeeded: false)`.
/// Tests never construct these; they inject fakes.

@MainActor
final class LiveTraceWorkspace: TraceWorkspace {
    func frontmost() -> TraceFrontApp? {
        guard let app = NSWorkspace.shared.frontmostApplication, let bundle = app.bundleIdentifier else { return nil }
        return TraceFrontApp(bundleId: bundle, name: app.localizedName ?? bundle, pid: app.processIdentifier)
    }

    func onActivation(_ handler: @escaping @MainActor () -> Void) -> AnyObject {
        let center = NSWorkspace.shared.notificationCenter
        let token = center.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil,
                                       queue: .main) { _ in
            MainActor.assumeIsolated { handler() }
        }
        return ObserverToken(center: center, token: token)
    }

    private final class ObserverToken {
        let center: NotificationCenter
        let token: NSObjectProtocol
        init(center: NotificationCenter, token: NSObjectProtocol) { self.center = center; self.token = token }
        deinit { center.removeObserver(token) }
    }
}

struct LiveTraceIdleProbe: TraceIdleProbe {
    func secondsSinceInput() -> TimeInterval {
        // Any input event (`kCGAnyInputEventType`), as seen by the HID system: no permission.
        CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: CGEventType(rawValue: ~0)!)
    }

    func screenLocked() -> Bool {
        guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
        return (session["CGSSessionScreenIsLocked"] as? Bool) == true || (session["kCGSSessionOnConsoleKey"] as? Bool) == false
    }

    func secureInput() -> Bool { IsSecureEventInputEnabled() }
}

struct LiveTraceWindowTitles: TraceWindowTitles {
    func trusted() -> Bool { AXIsProcessTrusted() }

    func focusedTitle(pid: Int32) -> String? {
        guard AXIsProcessTrusted() else { return nil }
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.25)
        var window: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let window, CFGetTypeID(window) == AXUIElementGetTypeID() else { return nil }
        var title: CFTypeRef?
        // swiftlint:disable:next force_cast
        guard AXUIElementCopyAttributeValue(window as! AXUIElement, kAXTitleAttribute as CFString, &title) == .success
        else { return nil }
        return title as? String
    }
}

/// A Chromium browser's front tab through in-process Apple Events, on one serial queue (NSAppleScript is not
/// thread-safe). Only after `granted` — which never asks.
final class LiveTraceBrowserTabs: TraceBrowserTabs, @unchecked Sendable {
    private let queue = DispatchQueue(label: "cicada.traces.tabs", qos: .utility)

    func granted(bundleId: String) -> Bool { ChromeFrontTab.granted(bundleId: bundleId) }

    func frontTab(bundleId: String) async -> TraceBrowserTab? {
        guard bundleId.range(of: #"^[A-Za-z0-9.\-]+$"#, options: .regularExpression) != nil else { return nil }
        let source = """
        tell application id "\(bundleId)"
            if (count of windows) is 0 then return ""
            set w to front window
            return (mode of w) & linefeed & (URL of active tab of w) & linefeed & (title of active tab of w)
        end tell
        """
        return await withCheckedContinuation { continuation in
            queue.async {
                var error: NSDictionary?
                let result = NSAppleScript(source: source)?.executeAndReturnError(&error).stringValue
                guard error == nil, let result, !result.isEmpty else { continuation.resume(returning: nil); return }
                let parts = result.components(separatedBy: "\n")
                guard parts.count >= 3 else { continuation.resume(returning: nil); return }
                continuation.resume(returning: TraceBrowserTab(url: parts[1], title: parts[2...].joined(separator: " "),
                                                               isPrivate: parts[0] != "normal"))
            }
        }
    }

    /// The person allowed this browser: the one moment the Automation prompt may appear (their click).
    static func ask(bundleId: String) -> Bool {
        var target = AEAddressDesc()
        let bytes = Array(bundleId.utf8)
        let created = bytes.withUnsafeBytes { raw in
            AECreateDesc(DescType(typeApplicationBundleID), raw.baseAddress, raw.count, &target)
        }
        guard created == noErr else { return false }
        defer { AEDisposeDesc(&target) }
        return AEDeterminePermissionToAutomateTarget(&target, AEEventClass(typeWildCard), AEEventID(typeWildCard),
                                                     true) == noErr
    }
}

struct LiveTraceScreenCapture: TraceScreenCapture {
    enum CaptureError: Error { case noAccess, noWindow, encode }

    func hasAccess() -> Bool { CGPreflightScreenCaptureAccess() }

    func captureFrontWindow(pid: Int32, maxSide: Int) async throws -> TraceCapturedFrame {
        // ScreenCaptureKit raises the Screen Recording prompt when access is missing: never reach it without the
        // preflight's yes.
        guard CGPreflightScreenCaptureAccess() else { throw CaptureError.noAccess }
        // The front window from the window server's front-to-back list, then that exact window in ScreenCaptureKit
        // (whose own list is unordered and counts covered windows as on screen — review of #456, B2).
        let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]] ?? []
        guard let frontID = TraceWindowPick.frontWindowID(in: info, pid: pid) else { throw CaptureError.noWindow }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        guard let window = content.windows.first(where: { $0.windowID == frontID && $0.owningApplication?.processID == pid })
        else { throw CaptureError.noWindow }
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let config = SCStreamConfiguration()
        let scale = min(1.0, Double(maxSide) / Double(max(window.frame.width, window.frame.height)))
        config.width = max(1, Int(window.frame.width * scale))
        config.height = max(1, Int(window.frame.height * scale))
        config.showsCursor = false
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
        guard let jpeg = Self.jpeg(image) else { throw CaptureError.encode }
        return TraceCapturedFrame(jpeg: jpeg, width: image.width, height: image.height)
    }

    static func jpeg(_ image: CGImage, quality: Double = 0.6) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        return CGImageDestinationFinalize(dest) ? data as Data : nil
    }
}

/// Apple's on-device recognizer. `usesLanguageCorrection` on, accurate level; nothing leaves this Mac.
/// Launch Services' https: handlers, refreshed every ten minutes (an app installed since is a browser soon after).
final class LiveTraceBrowserRegistry: TraceBrowserRegistry, @unchecked Sendable {
    private let lock = NSLock()
    private var ids: Set<String> = []
    private var readAt: Date?

    func opensWebLinks(_ bundleId: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if readAt == nil || Date().timeIntervalSince(readAt!) > 600 {
            var probe = URLComponents()
            probe.scheme = "https"
            probe.host = "example.invalid"   // never opened: only asks which apps are registered for the scheme
            if let url = probe.url {
                ids = Set(NSWorkspace.shared.urlsForApplications(toOpen: url).compactMap { Bundle(url: $0)?.bundleIdentifier })
            }
            readAt = Date()
        }
        return ids.contains(bundleId)
    }
}

struct LiveTraceTextRecognizer: TraceTextRecognizer {
    func recognize(jpeg: Data) async -> String {
        guard let source = CGImageSourceCreateWithData(jpeg as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return "" }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        let handler = VNImageRequestHandler(cgImage: image)
        do { try handler.perform([request]) } catch { return "" }
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        return lines.joined(separator: "\n")
    }
}

struct LiveTraceAuthenticator: TraceAuthenticator {
    func authenticate(reason: String) async -> Bool {
        let context = LAContext()
        context.touchIDAuthenticationAllowableReuseDuration = 0
        var error: NSError?
        // Touch ID, or the login password where there is none.
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { return false }
        return (try? await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) ?? false
    }
}

struct LiveTracePermissionProbe: TracePermissionProbe {
    func granted(_ permission: TracePermission) -> Bool {
        switch permission {
        case .accessibility: AXIsProcessTrusted()
        case .screenRecording: CGPreflightScreenCaptureAccess()
        case .fullDiskAccess: Self.opensProtectedFile()
        }
    }

    /// Full Disk Access has no preflight API and no prompt: the one honest look is opening a file only it unlocks — the
    /// two Cicada needs it for (Safari's bookmarks, Messages' database). `isReadableFile` checks POSIX bits alone, which
    /// say yes while macOS still refuses the open.
    static func opensProtectedFile(home: String = NSHomeDirectory()) -> Bool {
        for path in ["/Library/Safari/Bookmarks.plist", "/Library/Messages/chat.db"] {
            if let handle = FileHandle(forReadingAtPath: home + path) {
                try? handle.close()
                return true
            }
        }
        return false
    }
}
