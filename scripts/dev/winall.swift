import CoreGraphics
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in list {
  let owner = w[kCGWindowOwnerName as String] as? String ?? ""
  let layer = w[kCGWindowLayer as String] as? Int ?? -1
  let name = w[kCGWindowName as String] as? String ?? ""
  let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
  if layer == 0 { print(w[kCGWindowNumber as String]!, owner, "|", name, "|", b["Width"]!, "x", b["Height"]!, "@", b["X"]!, b["Y"]!) }
}
