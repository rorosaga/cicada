import Foundation

/// The prose half of an entity page, read the way the server reads it
/// (F1, owner review 2026-09-23; R-FX8).
///
/// `claims.write_claims` appends the ```claims fence after the page's last
/// section — there is no claims section anywhere — so a page whose only
/// section is `## Summary` carries its fence *inside* the Summary as far as a
/// line reader can tell. The server's readers strip it first
/// (`entity_body.summarize_for_recall`, `evidence.source_text`,
/// `state_dictionary`); this is the app's one copy of that rule, used by the
/// entity card's Summary box, body and media description and by the Feed
/// sheet. `MarkdownBody` already hides the fence as a code block; the leak was
/// the section readers.
enum EntityProse {
    private static let fence = String(repeating: "`", count: 3)

    /// The markdown with every ```claims block removed. An unterminated fence
    /// hides everything after it: showing machine YAML as prose is the defect
    /// this exists to prevent, and nothing prose-like follows a claims fence.
    ///
    /// Line semantics as before (a fence opens on a line that starts with ``` and
    /// trims to ```claims, closes on a line that trims to ```), but found by search
    /// instead of splitting every line: an owner-sized page is 2.6 MB and ~110k
    /// lines, almost all of them inside the fence, and the card read its Summary
    /// through this on every render (21 ms → under 1 ms in a debug build).
    static func stripClaimsFence(_ markdown: String) -> String {
        var text = markdown
        let kept: [String]? = text.withUTF8 { FenceScan(bytes: $0).keptRuns() }
        guard let kept else { return markdown.trimmingCharacters(in: .whitespacesAndNewlines) }
        return kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The text under a `## Header` up to the next `## ` header (or EOF), with
    /// the fence stripped first; nil when absent or empty.
    static func section(named header: String, in markdown: String) -> String? {
        let lines = stripClaimsFence(markdown).components(separatedBy: "\n")
        guard let start = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == header }) else {
            return nil
        }
        var body: [String] = []
        for line in lines[(start + 1)...] {
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("## ") { break }
            body.append(line)
        }
        let text = body.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    /// The first present, non-empty section among `headers`.
    static func firstSection(_ headers: [String], in markdown: String) -> String? {
        for header in headers {
            if let text = section(named: header, in: markdown) { return text }
        }
        return nil
    }

    /// `markdown` without the named `## Header` and its body (up to the next
    /// `## ` header or EOF). Used to drop sections that already have their own
    /// surface — the Summary box, the media Description card — so they don't
    /// render twice. Callers strip the fence first when the result is rendered.
    static func stripSection(named header: String, from markdown: String) -> String {
        let lines = markdown.components(separatedBy: "\n")
        guard let start = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == header }) else {
            return markdown
        }
        var kept = Array(lines[..<start])
        var i = start + 1
        while i < lines.count, !lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("## ") { i += 1 }
        kept.append(contentsOf: lines[i...])
        return kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// `agentic_write`'s old stub line (R-FX10). Pages keep it only when they
    /// have no open claim to write a sentence from; the card hides it (R-FX11).
    static func isPlaceholderSummary(_ text: String) -> Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
            .range(of: #"^[^\n]+ — created via agentic write\.$"#, options: .regularExpression) != nil
    }

    /// R-FX11 — a full page (never the graph-node stub, whose body is a
    /// one-line preview) whose prose is at most a Summary: its beliefs are the
    /// content worth showing.
    static func showsBeliefs(markdown: String, isStub: Bool) -> Bool {
        guard !isStub else { return false }
        let rest = stripSection(named: "## Summary", from: stripClaimsFence(markdown))
        return rest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

/// F4 — the page file verbatim, when the card has it: the inline `rawMarkdown`, or for a page whose fence the payload
/// withheld (`rawOmitted`, where `rawMarkdown` stops at the fence) only the file fetched from `/raw`. Nil means "not in
/// hand" — a caller never substitutes a reconstruction for a withheld file.
enum RawFile {
    static func verbatim(_ entity: Entity, fetched: String?) -> String? {
        if entity.rawOmitted { return fetched }
        return entity.rawMarkdown.isEmpty ? nil : entity.rawMarkdown
    }
}

/// F4 — reads `/entities/{id}/raw` for one card. `text` only ever holds a successful read; a failure sets `failed`
/// and leaves `text` nil, so the next attempt asks again.
@MainActor @Observable
final class RawFileLoader {
    private(set) var text: String?
    private(set) var failed = false
    private var loading = false

    func load(_ id: String, fetch: (String) async throws -> String) async {
        guard text == nil, !loading else { return }
        loading = true
        failed = false
        defer { loading = false }
        do {
            let raw = try await fetch(id)
            guard !Task.isCancelled else { return }
            text = raw
        } catch {
            if !Task.isCancelled { failed = true }
        }
    }
}

/// F4 — what the Source view draws. A page small enough is drawn whole; a larger one (an owner-sized page, ~2.6 MB, nearly
/// all of it claims fence) is drawn verbatim up to its first claims fence, with the rest's size in words — one `Text`
/// of megabytes stalls the card, and its beliefs are already the Perspectives tab.
enum SourceText {
    static let drawLimit = 256 * 1024

    static func shown(_ raw: String, limit: Int = drawLimit) -> (text: String, foldedBytes: Int?) {
        let total = raw.utf8.count
        guard total > limit else { return (raw, nil) }
        var bytes = raw
        let cut: Int = bytes.withUTF8 { buffer in
            guard let base = buffer.baseAddress else { return limit }
            let needle = Array("\n```claims".utf8)
            let hit = needle.withUnsafeBytes { memmem(base, buffer.count, $0.baseAddress, $0.count) }
            return hit.map { base.distance(to: $0.assumingMemoryBound(to: UInt8.self)) + 1 } ?? limit
        }
        let head = String(decoding: raw.utf8.prefix(min(cut, limit)), as: UTF8.self)
        return (head, total - head.utf8.count)
    }
}

/// `EntityProse.stripClaimsFence` over the page's UTF-8 bytes: `memmem`/`memchr` find the fences, and only the few
/// lines that might open or close one become strings.
private struct FenceScan {
    let bytes: UnsafeBufferPointer<UInt8>
    private static let open = Array("```claims".utf8)
    private static let tick = Array("```".utf8)
    private static let newline = UInt8(ascii: "\n")

    /// Kept runs of whole lines, each without the newline that ends its last line — joined by "\n" they are exactly
    /// the kept lines joined by "\n" — or nil when there is no fence to look at.
    func keptRuns() -> [String]? {
        let length = bytes.count
        guard find(Self.open, from: 0) != nil else { return nil }
        var kept: [String] = []
        var runStart = 0        // a line start: the first line of the current kept run
        var scan = 0            // a line start: where to look for the next opening
        var hasTail = true      // the run from `runStart` holds at least one line
        while scan < length, let at = find(Self.open, from: scan) {
            let opening = line(around: at, floor: scan)
            let words = string(opening.start, opening.end)
            guard words.hasPrefix("```"), words.trimmingCharacters(in: .whitespacesAndNewlines) == "```claims" else {
                scan = opening.end + 1
                continue
            }
            if opening.start > runStart { kept.append(string(runStart, opening.start - 1)) }
            var search = opening.end + 1
            var closed: (start: Int, end: Int)?
            while search < length, let mark = find(Self.tick, from: search) {
                let candidate = line(around: mark, floor: search)
                if string(candidate.start, candidate.end).trimmingCharacters(in: .whitespacesAndNewlines) == "```" {
                    closed = candidate
                    break
                }
                search = candidate.end + 1
            }
            guard let closed, closed.end < length else {
                hasTail = false   // unterminated, or the closing line is the last: nothing follows
                break
            }
            runStart = closed.end + 1
            scan = runStart
        }
        if hasTail { kept.append(string(runStart, length)) }
        return kept
    }

    private func find(_ needle: [UInt8], from: Int) -> Int? {
        guard from < bytes.count, let base = bytes.baseAddress else { return nil }
        return needle.withUnsafeBytes { n -> Int? in
            guard let hit = memmem(base + from, bytes.count - from, n.baseAddress, n.count) else { return nil }
            return base.distance(to: hit.assumingMemoryBound(to: UInt8.self))
        }
    }

    /// The line holding `index`, never reaching back before `floor` (itself a line start).
    private func line(around index: Int, floor: Int) -> (start: Int, end: Int) {
        var start = index
        while start > floor, bytes[start - 1] != Self.newline { start -= 1 }
        guard let base = bytes.baseAddress,
              let hit = memchr(base + index, Int32(Self.newline), bytes.count - index) else { return (start, bytes.count) }
        return (start, base.distance(to: hit.assumingMemoryBound(to: UInt8.self)))
    }

    private func string(_ start: Int, _ end: Int) -> String {
        String(decoding: UnsafeBufferPointer(rebasing: bytes[start..<max(start, end)]), as: UTF8.self)
    }
}
