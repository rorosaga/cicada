import Foundation
// Builds attributedBody blobs the way Messages does: an NSMutableAttributedString archived with NSArchiver (typedstream),
// carrying Messages' own part/direction attributes. Text is synthetic.
func blob(_ s: String, parts: Bool, link: Bool = false) -> Data {
    let m = NSMutableAttributedString(string: s)
    let len = (s as NSString).length
    if parts {
        m.addAttribute(NSAttributedString.Key("__kIMMessagePartAttributeName"), value: NSNumber(value: 0), range: NSRange(location: 0, length: len))
        m.addAttribute(NSAttributedString.Key("__kIMBaseWritingDirectionAttributeName"), value: "-1", range: NSRange(location: 0, length: len))
    }
    if link, len > 4 {
        m.addAttribute(NSAttributedString.Key("__kIMLinkAttributeName"), value: NSURL(string: "https://example.com/a")!, range: NSRange(location: 0, length: 4))
    }
    return NSArchiver.archivedData(withRootObject: m)
}
let cases: [(String, String, Bool, Bool)] = [
    ("plain", "Thanks, that helps a lot.", true, false),
    ("no_attributes", "ok", false, false),
    ("emoji", "Sounds good 👍🏽 see you at 6 — café?", true, false),
    ("attachment_only", "\u{FFFC}", true, false),
    ("attachment_and_text", "\u{FFFC}Here is the plan for alpha-project.", true, false),
    ("len_127", String(repeating: "a", count: 127), true, false),
    ("len_128", String(repeating: "b", count: 128), true, false),
    ("len_129", String(repeating: "c", count: 129), true, false),
    ("len_300", String(repeating: "Instinct reply line. ", count: 15), true, false),
    ("len_40000", String(repeating: "x", count: 40000), true, false),
    ("len_70000", String(repeating: "y", count: 70000), true, false),
    ("multiline", "Step one: draft the outline.\nStep two: send it to bob-example.\nuser: not a turn", true, false),
    ("with_link", "Read https://example.com/a tonight", true, true),
]
var out: [[String: String]] = []
for (name, s, parts, link) in cases {
    let d = blob(s, parts: parts, link: link)
    out.append(["name": name, "text": s, "hex": d.map { String(format: "%02x", $0) }.joined()])
}
let json = try! JSONSerialization.data(withJSONObject: ["generator": "NSArchiver.archivedData(withRootObject: NSMutableAttributedString)", "macOS": ProcessInfo.processInfo.operatingSystemVersionString, "cases": out], options: [.prettyPrinted, .sortedKeys])
FileManager.default.createFile(atPath: CommandLine.arguments[1], contents: json)
