import XCTest
@testable import CicadaApp

/// A byte-at-a-time `AsyncSequence` standing in for `URLSession.AsyncBytes`.
private struct ByteStream: AsyncSequence, Sendable {
    typealias Element = UInt8
    let bytes: [UInt8]
    init(_ s: String) { bytes = Array(s.utf8) }
    struct Iterator: AsyncIteratorProtocol {
        var i = 0
        let bytes: [UInt8]
        mutating func next() async throws -> UInt8? {
            guard i < bytes.count else { return nil }
            defer { i += 1 }
            return bytes[i]
        }
    }
    func makeAsyncIterator() -> Iterator { Iterator(bytes: bytes) }
}

/// The exact byte sequence `api/routers/sync.py` emits.
private let backendFrames = """
event: version
data: {"version": "aaa", "components": {"entities": "1"}}

event: sleep
data: {"status": "idle", "stage": 0, "totalStages": 5}

event: ping
data: {}

event: version
data: {"version": "bbb", "components": {"entities": "2"}}


"""

final class SSELineSplitterTests: XCTestCase {

    private func collect(_ text: String) async throws -> [String] {
        var out: [String] = []
        for try await line in SSELineSplitter.lines(from: ByteStream(text)) { out.append(line) }
        return out
    }

    /// The bug, pinned. Foundation's `AsyncLineSequence` only yields when its
    /// buffer is non-empty, so every SSE frame terminator vanishes. If this
    /// ever starts failing, Apple fixed it and the splitter could go away.
    func testFoundationAsyncLineSequenceDropsEmptyLines() async throws {
        var out: [String] = []
        for try await line in ByteStream("a\n\nb\n").lines { out.append(line) }
        if out.contains("") {
            throw XCTSkip("Foundation now preserves blank lines — SSELineSplitter may be redundant")
        }
        XCTAssertEqual(out, ["a", "b"], "AsyncLineSequence is expected to swallow blank lines")
    }

    func testSplitterPreservesEmptyLines() async throws {
        let a = try await collect("a\n\nb\n")
        XCTAssertEqual(a, ["a", "", "b"])
        let b = try await collect("\n\n\n")
        XCTAssertEqual(b, ["", "", ""])
    }

    func testSplitterTrimsCarriageReturnsAndYieldsTrailingPartial() async throws {
        let out = try await collect("a\r\n\r\nb")
        XCTAssertEqual(out, ["a", "", "b"])
    }

    func testSplitterEmptyInputYieldsNothing() async throws {
        let out = try await collect("")
        XCTAssertTrue(out.isEmpty)
    }

    /// End to end: the real backend byte sequence must produce the real events,
    /// in order, including the *second* `version` — the one the app never saw.
    func testBackendFramesParseIntoEveryEvent() async throws {
        var parser = SSEParser()
        var events: [SSEEvent] = []
        for try await line in SSELineSplitter.lines(from: ByteStream(backendFrames)) {
            if let e = parser.feed(line) { events.append(e) }
        }
        XCTAssertEqual(events.map(\.name), ["version", "sleep", "ping", "version"])
        XCTAssertEqual(events[0].data, #"{"version": "aaa", "components": {"entities": "1"}}"#)
        XCTAssertEqual(events[3].data, #"{"version": "bbb", "components": {"entities": "2"}}"#)

        // Decoding the second one must yield a usable vector — the whole point.
        let v = try JSONDecoder().decode(VersionVector.self, from: Data(events[3].data.utf8))
        XCTAssertEqual(v.version, "bbb")
        XCTAssertEqual(v.components["entities"], "2")
    }

    /// The pre-fix behaviour, pinned as the counter-example: feeding the same
    /// frames through `AsyncLineSequence` yields ZERO events.
    func testBackendFramesThroughAsyncLineSequenceYieldNoEvents() async throws {
        var parser = SSEParser()
        var events: [SSEEvent] = []
        for try await line in ByteStream(backendFrames).lines {
            if let e = parser.feed(line) { events.append(e) }
        }
        if !events.isEmpty {
            throw XCTSkip("Foundation now preserves blank lines — SSELineSplitter may be redundant")
        }
        XCTAssertTrue(events.isEmpty, "blank-line-free input can never terminate an SSE frame")
    }

    /// Multi-byte UTF-8 must survive the byte-level split. The splitter
    /// accumulates raw bytes and decodes once per line, so a character whose
    /// encoding straddles the arbitrary chunk boundaries the transport hands
    /// us (the stream here is delivered one byte at a time — the worst case)
    /// must still come out intact.
    func testSplitterHandlesMultiByteUTF8AcrossChunks() async throws {
        let payload = #"{"name": "Raúl Pérez Peláez", "note": "π0.7 — 🐝 consolidación"}"#
        var parser = SSEParser()
        var events: [SSEEvent] = []
        for try await line in SSELineSplitter.lines(from: ByteStream("event: version\ndata: \(payload)\n\n")) {
            if let e = parser.feed(line) { events.append(e) }
        }
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events.first?.data, payload)

        // And the same bytes as bare lines, with the multi-byte run adjacent
        // to the terminators on both sides.
        let lines = try await collect("é\n\n🐝\n")
        XCTAssertEqual(lines, ["é", "", "🐝"])
    }
}
