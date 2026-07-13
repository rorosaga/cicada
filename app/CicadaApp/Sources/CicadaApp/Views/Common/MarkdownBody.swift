import SwiftUI

// MARK: - MarkdownBody
//
// A minimal native markdown BLOCK renderer for entity-page prose. Consumes one
// raw text segment as tokenized by `TranscludingMarkdownView` (i.e. already
// stripped of `![[embed]]` / `![alt](url)` tokens — those remain separate
// `.embed` / `.image` segments handled there) and renders headings, bullet/
// ordered lists, fenced code blocks, blockquotes, horizontal rules, and
// paragraphs with `CicadaTheme` styling.
//
// Inline spans (bold/italic/inline-code/real `[text](url)` links) are handled
// by `AttributedString(markdown:)` in one pass. `[[Wikilinks]]` /
// `[[id|Alias]]` are rewritten into ordinary markdown links pointed at a
// synthetic `cicada://entity/<id>` URL *before* that parse, so a wikilink
// gets exactly the same treatment as any other link instead of needing a
// second attribute-surgery step afterward. `TranscludingMarkdownView` installs
// the `\.openURL` handler that intercepts the `cicada:` scheme and routes it
// to `graphVM.selectEntity(id:)`; everything else (http/https) falls through
// to the system (opens in the browser).
//
// The `` ```claims `` fence (machine-owned relation data written by
// `api/services/claims.py`) is parsed as an ordinary code block — so it still
// can't leak into surrounding blocks — but is SKIPPED at render time. Claims
// already have a dedicated surface (EntityDetailCard's Perspectives/Timeline
// tabs); re-showing the raw YAML inline in the reading pane would just be
// noise, not prose.
struct MarkdownBody: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(Array(MarkdownBlockParser.parse(text).enumerated()), id: \.offset) { _, block in
                blockView(block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock) -> some View {
        switch block {
        case .heading(let level, let raw):
            Text(Self.inlineAttributed(raw))
                .font(Self.headingFont(level))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .padding(.top, level <= 2 ? CicadaTheme.spacingSM : CicadaTheme.spacingXS)
                .frame(maxWidth: .infinity, alignment: .leading)

        case .paragraph(let raw):
            Text(Self.inlineAttributed(raw))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)

        case .list(let items):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .top, spacing: 6) {
                        Text(item.marker)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .frame(minWidth: 16, alignment: .trailing)
                        Text(Self.inlineAttributed(item.text))
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.leading, CGFloat(item.indent) * 14)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

        case .codeBlock(let lang, let code):
            if lang.lowercased() == "claims" {
                // Machine data, not prose — see file header. Render nothing.
                EmptyView()
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    Text(code)
                        .font(CicadaTheme.monoFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .textSelection(.enabled)
                        .padding(CicadaTheme.spacingSM)
                }
                .background(CicadaTheme.surface)
                .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .stroke(CicadaTheme.border, lineWidth: 1)
                )
                .frame(maxWidth: .infinity, alignment: .leading)
            }

        case .blockquote(let raw):
            HStack(alignment: .top, spacing: 0) {
                Rectangle()
                    .fill(CicadaTheme.accent.opacity(0.6))
                    .frame(width: 3)
                Text(Self.inlineAttributed(raw))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .italic()
                    .textSelection(.enabled)
                    .padding(.leading, CicadaTheme.spacingSM)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

        case .rule:
            Divider()
                .background(CicadaTheme.border)
                .padding(.vertical, 2)
        }
    }

    private static func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return CicadaTheme.titleFont
        case 2: return CicadaTheme.headingFont
        case 3: return CicadaTheme.bodyFont.weight(.semibold)
        default: return CicadaTheme.captionFont.weight(.semibold)
        }
    }

    // MARK: - Inline rendering

    /// Renders one line/paragraph's worth of inline markdown (bold, italic,
    /// inline code, real `[text](url)` links) after rewriting wikilinks into
    /// ordinary markdown links. Falls back to a plain (but still-linkified)
    /// string if the markdown parse throws on malformed input.
    static func inlineAttributed(_ raw: String) -> AttributedString {
        let prepped = linkifyWikilinks(raw)
        var attr: AttributedString
        if let parsed = try? AttributedString(
            markdown: prepped,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            attr = parsed
        } else {
            attr = AttributedString(prepped)
        }

        // Base color for runs the parser left uncolored (i.e. everything that
        // isn't a link).
        for run in attr.runs where run.foregroundColor == nil {
            attr[run.range].foregroundColor = CicadaTheme.textPrimary
        }
        // Both wikilinks (cicada://) and real markdown links get the same
        // accent + underline treatment so a tappable span always reads as one.
        for run in attr.runs where run.link != nil {
            attr[run.range].foregroundColor = CicadaTheme.accent
            attr[run.range].underlineStyle = .single
        }
        return attr
    }

    /// `[[Entity Name]]` → `[Entity Name](cicada://entity/entity-name)`;
    /// `[[id|Alias]]` → `[Alias](cicada://entity/id)`. Id sanitization
    /// mirrors the convention used elsewhere for ref → entity-id resolution:
    /// lowercase, runs of non-alphanumerics collapsed to a single `-`, trimmed.
    private static func linkifyWikilinks(_ text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: "\\[\\[([^\\[\\]|]+)(?:\\|([^\\[\\]]+))?\\]\\]") else {
            return text
        }
        let ns = text as NSString
        var out = ""
        var lastEnd = 0
        for match in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: lastEnd, length: match.range.location - lastEnd))
            let name = ns.substring(with: match.range(at: 1)).trimmingCharacters(in: .whitespaces)
            let alias = match.range(at: 2).location != NSNotFound
                ? ns.substring(with: match.range(at: 2)).trimmingCharacters(in: .whitespaces)
                : nil
            let display = alias ?? name
            let id = sanitizeID(name)
            out += "[\(display)](cicada://entity/\(id))"
            lastEnd = match.range.location + match.range.length
        }
        out += ns.substring(from: lastEnd)
        return out
    }

    private static func sanitizeID(_ raw: String) -> String {
        let lowered = raw.lowercased()
        var result = ""
        var lastWasDash = false
        for scalar in lowered.unicodeScalars {
            if CharacterSet.alphanumerics.contains(scalar) {
                result.unicodeScalars.append(scalar)
                lastWasDash = false
            } else if !lastWasDash {
                result += "-"
                lastWasDash = true
            }
        }
        return result.trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    }
}

// MARK: - Block model + parser

private enum MarkdownBlock {
    case heading(level: Int, text: String)
    case paragraph(text: String)
    case list(items: [MarkdownListItem])
    case codeBlock(lang: String, code: String)
    case blockquote(text: String)
    case rule
}

private struct MarkdownListItem {
    let indent: Int
    let marker: String
    let text: String
}

/// Line-based block splitter. Deliberately simple (no nested blockquotes, no
/// multi-level list continuation lines) — entity bodies are a few KB of fairly
/// flat prose, not arbitrary CommonMark documents.
private enum MarkdownBlockParser {
    private static let headingRegex = try? NSRegularExpression(pattern: "^(#{1,6})\\s+(.*)$")
    private static let ruleRegex = try? NSRegularExpression(pattern: "^(-{3,}|\\*{3,}|_{3,})\\s*$")
    private static let bulletRegex = try? NSRegularExpression(pattern: "^(\\s*)[-*+]\\s+(.*)$")
    private static let orderedRegex = try? NSRegularExpression(pattern: "^(\\s*)(\\d+)\\.\\s+(.*)$")
    private static let quoteRegex = try? NSRegularExpression(pattern: "^\\s*>\\s?(.*)$")

    static func parse(_ raw: String) -> [MarkdownBlock] {
        guard headingRegex != nil, ruleRegex != nil, bulletRegex != nil,
              orderedRegex != nil, quoteRegex != nil else {
            return [.paragraph(text: raw)]
        }

        let lines = raw.components(separatedBy: "\n")
        var blocks: [MarkdownBlock] = []
        var i = 0
        let n = lines.count

        func fenceLang(_ line: String) -> String? {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("```") else { return nil }
            return String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
        }

        func firstMatch(_ regex: NSRegularExpression?, _ s: String) -> NSTextCheckingResult? {
            guard let regex else { return nil }
            return regex.firstMatch(in: s, range: NSRange(location: 0, length: (s as NSString).length))
        }

        func isListLine(_ s: String) -> Bool {
            firstMatch(bulletRegex, s) != nil || firstMatch(orderedRegex, s) != nil
        }

        while i < n {
            let line = lines[i]
            let trimmedLine = line.trimmingCharacters(in: .whitespaces)

            if trimmedLine.isEmpty {
                i += 1
                continue
            }

            // Fenced code block — everything up to the closing fence is verbatim.
            if let lang = fenceLang(line) {
                var codeLines: [String] = []
                i += 1
                while i < n, fenceLang(lines[i]) == nil {
                    codeLines.append(lines[i])
                    i += 1
                }
                if i < n { i += 1 } // consume closing fence
                blocks.append(.codeBlock(lang: lang, code: codeLines.joined(separator: "\n")))
                continue
            }

            // Heading.
            if let m = firstMatch(headingRegex, line) {
                let ns = line as NSString
                let level = ns.substring(with: m.range(at: 1)).count
                let text = ns.substring(with: m.range(at: 2))
                blocks.append(.heading(level: level, text: text))
                i += 1
                continue
            }

            // Horizontal rule.
            if firstMatch(ruleRegex, trimmedLine) != nil {
                blocks.append(.rule)
                i += 1
                continue
            }

            // Blockquote — collect consecutive `>` lines into one block.
            if firstMatch(quoteRegex, line) != nil {
                var quoteLines: [String] = []
                while i < n, let m = firstMatch(quoteRegex, lines[i]) {
                    let ns = lines[i] as NSString
                    quoteLines.append(ns.substring(with: m.range(at: 1)))
                    i += 1
                }
                blocks.append(.blockquote(text: quoteLines.joined(separator: " ")))
                continue
            }

            // List — collect consecutive bullet/ordered lines (tolerating a
            // single blank line between items of the same tight list).
            if isListLine(line) {
                var items: [MarkdownListItem] = []
                while i < n {
                    let l = lines[i]
                    if let m = firstMatch(bulletRegex, l) {
                        let ns = l as NSString
                        let indent = ns.substring(with: m.range(at: 1)).count
                        let text = ns.substring(with: m.range(at: 2))
                        items.append(MarkdownListItem(indent: indent / 2, marker: "•", text: text))
                        i += 1
                    } else if let m = firstMatch(orderedRegex, l) {
                        let ns = l as NSString
                        let indent = ns.substring(with: m.range(at: 1)).count
                        let num = ns.substring(with: m.range(at: 2))
                        let text = ns.substring(with: m.range(at: 3))
                        items.append(MarkdownListItem(indent: indent / 2, marker: "\(num).", text: text))
                        i += 1
                    } else if l.trimmingCharacters(in: .whitespaces).isEmpty,
                              i + 1 < n, isListLine(lines[i + 1]) {
                        i += 1 // blank line inside a tight list — keep going
                    } else {
                        break
                    }
                }
                blocks.append(.list(items: items))
                continue
            }

            // Paragraph — consecutive plain lines, soft-wrapped into one Text.
            var paraLines: [String] = []
            while i < n {
                let l = lines[i]
                let t = l.trimmingCharacters(in: .whitespaces)
                if t.isEmpty { break }
                if fenceLang(l) != nil { break }
                if firstMatch(headingRegex, l) != nil { break }
                if firstMatch(ruleRegex, t) != nil { break }
                if firstMatch(quoteRegex, l) != nil { break }
                if isListLine(l) { break }
                paraLines.append(l)
                i += 1
            }
            blocks.append(.paragraph(text: paraLines.joined(separator: " ")))
        }
        return blocks
    }
}
