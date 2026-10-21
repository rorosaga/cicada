// Window lookup and real clicks for ONE process id, so a verify run never touches another Cicada.
// Built once per run by `cv app build` (swiftc -O -o <run>/bin/winctl winctl.swift).
//   winctl windows <pid>             JSON list of on-screen windows owned by <pid>
//   winctl activate <pid>            bring that process frontmost
//   winctl click <pid> <x> <y>       activate, then a real left click at window-relative points (top-left origin),
//                                    refused outside the window or when another process's window is topmost there
import AppKit
import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}

func windows(of pid: pid_t) -> [[String: Any]] {
    let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
        as? [[String: Any]] ?? []
    return info.compactMap { w in
        guard (w[kCGWindowOwnerPID as String] as? Int).map({ pid_t($0) }) == pid,
              (w[kCGWindowLayer as String] as? Int) == 0,
              let id = w[kCGWindowNumber as String] as? Int,
              let b = w[kCGWindowBounds as String] as? [String: Double] else { return nil }
        return ["id": id, "title": w[kCGWindowName as String] as? String ?? "",
                "x": b["X"] ?? 0, "y": b["Y"] ?? 0, "width": b["Width"] ?? 0, "height": b["Height"] ?? 0]
    }
}

func topmostOwner(at point: CGPoint) -> pid_t? {
    let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
        as? [[String: Any]] ?? []
    for w in info {
        guard let b = w[kCGWindowBounds as String] as? [String: Double],
              (w[kCGWindowAlpha as String] as? Double ?? 1) > 0 else { continue }
        let rect = CGRect(x: b["X"] ?? 0, y: b["Y"] ?? 0, width: b["Width"] ?? 0, height: b["Height"] ?? 0)
        if rect.contains(point) { return (w[kCGWindowOwnerPID as String] as? Int).map { pid_t($0) } }
    }
    return nil
}

func activate(_ pid: pid_t) {
    guard let app = NSRunningApplication(processIdentifier: pid) else { fail("no running application with pid \(pid)") }
    app.activate(options: [.activateAllWindows])
    for _ in 0..<20 {
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == pid { return }
        usleep(100_000)
    }
    fail("pid \(pid) did not become frontmost")
}

let args = CommandLine.arguments
guard args.count >= 3, let pid = pid_t(args[2]) else { fail("usage: winctl windows|activate|click <pid> [x y]") }
switch args[1] {
case "windows":
    let data = try! JSONSerialization.data(withJSONObject: windows(of: pid), options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
case "activate":
    activate(pid)
case "click":
    guard args.count == 5, let x = Double(args[3]), let y = Double(args[4]) else { fail("usage: winctl click <pid> <x> <y>") }
    guard let w = windows(of: pid).max(by: { ($0["width"] as! Double) * ($0["height"] as! Double)
        < ($1["width"] as! Double) * ($1["height"] as! Double) }) else { fail("pid \(pid) has no on-screen window") }
    let width = w["width"] as! Double, height = w["height"] as! Double
    guard x >= 0, y >= 0, x < width, y < height else { fail("(\(x), \(y)) is outside the window (\(width) x \(height))") }
    activate(pid)
    let point = CGPoint(x: (w["x"] as! Double) + x, y: (w["y"] as! Double) + y)
    guard let top = topmostOwner(at: point), top == pid else {
        fail("another process's window is topmost at (\(x), \(y)); nothing was clicked")
    }
    let source = CGEventSource(stateID: .hidSystemState)
    for type in [CGEventType.mouseMoved, .leftMouseDown, .leftMouseUp] {
        let event = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: .left)!
        event.post(tap: .cghidEventTap)
        usleep(60_000)
    }
    print("clicked window \(w["id"]!) at (\(x), \(y))")
default:
    fail("unknown verb \(args[1])")
}
