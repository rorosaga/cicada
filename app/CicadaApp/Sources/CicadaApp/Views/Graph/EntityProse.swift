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
    static func stripClaimsFence(_ markdown: String) -> String {
        var kept: [String] = []
        var inFence = false
        for line in markdown.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if inFence {
                if trimmed == fence { inFence = false }
                continue
            }
            if line.hasPrefix(fence), trimmed == fence + "claims" {
                inFence = true
                continue
            }
            kept.append(line)
        }
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
