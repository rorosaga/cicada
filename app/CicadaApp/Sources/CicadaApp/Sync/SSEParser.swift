import Foundation

struct SSEEvent: Equatable { let name: String; let data: String }

/// Splits a raw byte stream into `text/event-stream` lines — **including the
/// empty ones**.
///
/// Why this exists instead of `URLSession.AsyncBytes.lines`: Foundation's
/// `AsyncLineSequence` only yields when its accumulated buffer is non-empty, so
/// it *silently drops every blank line*. A blank line is SSE's one and only
/// frame terminator, and `SSEParser` emits an event exactly when it sees one —
/// so over `.lines` the parser accumulates fields forever and never returns an
/// event. Symptom: the app connects, receives bytes promptly (verified with a
/// `URLSessionDataDelegate` probe), and never reacts to a single `version`
/// event. See `.superpowers/sdd/2026-08-30-sync-engine/task-sse-fix-report.md`.
enum SSELineSplitter {
    /// `\n`-delimited lines, `\r` trimmed, empty lines preserved. The trailing
    /// partial line (no terminator before EOF) is yielded on clean close.
    static func lines<S: AsyncSequence & Sendable>(
        from bytes: S
    ) -> AsyncThrowingStream<String, any Error> where S.Element == UInt8 {
        AsyncThrowingStream { continuation in
            let task = Task {
                var buffer: [UInt8] = []
                do {
                    for try await byte in bytes {
                        guard byte != 0x0A else {  // \n
                            if buffer.last == 0x0D { buffer.removeLast() }  // \r
                            continuation.yield(String(decoding: buffer, as: UTF8.self))
                            buffer.removeAll(keepingCapacity: true)
                            continue
                        }
                        buffer.append(byte)
                    }
                    if !buffer.isEmpty {
                        continuation.yield(String(decoding: buffer, as: UTF8.self))
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

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
