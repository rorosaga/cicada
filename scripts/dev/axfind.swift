import Cocoa
import ApplicationServices
// usage: axfind <substring> [press]
let args = CommandLine.arguments
let needle = args.count > 1 ? args[1] : ""
let press = args.count > 2 && args[2] == "press"
guard let app = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == "CicadaApp" || $0.bundleIdentifier?.contains("cicada") == true && $0.activationPolicy == .regular }) else { print("no app"); exit(1) }
let axApp = AXUIElementCreateApplication(app.processIdentifier)
func attr(_ e: AXUIElement, _ a: String) -> AnyObject? { var v: AnyObject?; AXUIElementCopyAttributeValue(e, a as CFString, &v); return v }
var found = 0
func walk(_ e: AXUIElement, _ depth: Int) {
    if depth > 40 || found > 5 { return }
    let role = attr(e, kAXRoleAttribute) as? String ?? ""
    let desc = (attr(e, kAXDescriptionAttribute) as? String ?? "") + "|" + (attr(e, kAXTitleAttribute) as? String ?? "") + "|" + ((attr(e, kAXValueAttribute) as? String) ?? "")
    if !needle.isEmpty && desc.localizedCaseInsensitiveContains(needle) && (role == "AXButton" || role == "AXCell" || role == "AXRow" || role == "AXStaticText" || role == "AXGroup") {
        found += 1
        print(role, desc.prefix(90))
        if press && role == "AXButton" { let r = AXUIElementPerformAction(e, kAXPressAction as CFString); print("press ->", r.rawValue); exit(0) }
    }
    if let kids = attr(e, kAXChildrenAttribute) as? [AXUIElement] { for k in kids { walk(k, depth + 1) } }
}
if let wins = attr(axApp, kAXWindowsAttribute) as? [AXUIElement] { for w in wins { walk(w, 0) } }
