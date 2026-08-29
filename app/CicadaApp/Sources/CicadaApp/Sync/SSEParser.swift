import Foundation

struct SSEEvent: Equatable { let name: String; let data: String }

/// Minimal text/event-stream parser: feed one line at a time; an event is
/// returned on the blank line that terminates it.
struct SSEParser {
    private var name = "message"
    private var data: [String] = []

    mutating func feed(_ rawLine: String) -> SSEEvent? {
        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
        if line.isEmpty {
            guard !data.isEmpty else { name = "message"; return nil }
            let event = SSEEvent(name: name, data: data.joined(separator: "\n"))
            name = "message"; data = []
            return event
        }
        if line.hasPrefix(":") { return nil }
        let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        let field = String(parts[0])
        var value = parts.count > 1 ? String(parts[1]) : ""
        if value.hasPrefix(" ") { value.removeFirst() }
        switch field {
        case "event": name = value
        case "data": data.append(value)
        default: break
        }
        return nil
    }
}
