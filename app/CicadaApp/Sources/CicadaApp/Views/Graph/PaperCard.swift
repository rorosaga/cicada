import AppKit
import SwiftUI

/// Every sentence the paper card and the Feed row say, as pure functions — so a
/// reviewer reads the rule, and `PaperCardTests` pins it.
enum PaperCardText {
    /// "Ada Example, Bob Example · Journal of Examples · 2024" — three authors
    /// at most, then "et al.".
    static func byline(authors: [String], venue: String?, published: String?) -> String {
        var parts: [String] = []
        if !authors.isEmpty {
            parts.append(authors.count > 3 ? authors.prefix(3).joined(separator: ", ") + " et al."
                                           : authors.joined(separator: ", "))
        }
        if let venue, !venue.isEmpty { parts.append(venue) }
        if let year = published?.prefix(4), year.count == 4 { parts.append(String(year)) }
        return parts.joined(separator: " · ")
    }

    /// The Feed row's short form: "Ada Example et al. · 2024".
    static func feedLine(_ paper: PaperSummary) -> String? {
        var parts: [String] = []
        if let first = paper.authors.first { parts.append(paper.authors.count > 1 ? "\(first) et al." : first) }
        if let year = paper.published?.prefix(4), year.count == 4 { parts.append(String(year)) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// "Why you saved it", "Cited in alpha-project", "Filed under Retrieval".
    static func label(_ item: PaperWhyItem) -> String {
        switch item.predicate {
        case "saved-because": "Why you saved it"
        case "cited-in": "Cited in \(item.target ?? "your project")"
        case "about": "Filed under \(item.target ?? item.heading ?? "a topic")"
        default: item.predicate
        }
    }

    /// "REFERENCES.md › Retrieval · edited 2026-09-01" — file, heading, date.
    static func whereLine(_ item: PaperWhyItem) -> String {
        var place = item.file ?? "a note"
        if let heading = item.heading, !heading.isEmpty { place += " › \(heading)" }
        if let edited = item.edited { place += " · edited \(edited)" }
        if item.kind == "assistant" { place += " · written by an agent" }
        return place
    }

    static func contextHeading(source: String?, asOf: String?) -> String {
        let from = source == "crossref" ? "Crossref" : "arXiv"
        guard let asOf else { return "Context (from \(from))" }
        return "Context (from \(from), as of \(asOf))"
    }

    static let agentOnly = "Found by an agent's research sweep — not cited in your own notes."
    static let noWhy = "Nothing you wrote cites this paper right now."
    static let noContext = "Details from arXiv haven't been fetched yet — they arrive with the next sync."
}

/// G133 / G121 — a paper page leads with why it is in the person's memory,
/// each reason a quote from their own file with where it sits, and puts the
/// fetched abstract underneath as dated context. Replaces the link preview
/// for a paper: the card never loads arxiv.org itself (R-LS19).
struct PaperCard: View {
    let detail: PaperDetail

    /// R-LS28 — New York italic for a provenance quote; the Meadow `quoteFont`
    /// replaces this when M1 lands (the M2 pass).
    private var quote: Font { CicadaTheme.font(size: 13, design: .serif).italic() }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            let byline = PaperCardText.byline(authors: detail.authors, venue: detail.venue, published: detail.published)
            if !byline.isEmpty {
                Text(byline)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if let abs = detail.absUrl, let url = URL(string: abs) {
                    Button("Open on arXiv") { NSWorkspace.shared.open(url) }.buttonStyle(.bordered)
                }
                if let doi = detail.doiUrl, let url = URL(string: doi) {
                    Button("Open DOI") { NSWorkspace.shared.open(url) }.buttonStyle(.bordered)
                }
            }

            Text("Why it's in your memory")
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            if detail.agentOnly {
                Text(PaperCardText.agentOnly)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.warning)
            }
            if detail.why.isEmpty {
                Text(PaperCardText.noWhy)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(detail.why) { item in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(PaperCardText.label(item))
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text(highlighted(item))
                        .font(quote)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(PaperCardText.whereLine(item))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .padding(CicadaTheme.spacingSM)
                .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.surface))
            }

            Divider().background(CicadaTheme.border)
            Text(PaperCardText.contextHeading(source: detail.contextSource, asOf: detail.contextAsOf))
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(detail.context ?? PaperCardText.noContext)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(detail.context == nil ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// The cited words bold inside their sentence; a stale span shows the
    /// sentence plainly rather than highlighting words that may have moved (G118 R2).
    private func highlighted(_ item: PaperWhyItem) -> AttributedString {
        var text = AttributedString(item.snippet)
        // The server's offsets count Unicode scalars (Python `str` indices), so
        // the highlight is placed on the scalar view, not on grapheme clusters.
        let scalars = text.unicodeScalars
        guard !item.stale, item.highlightStart >= 0, item.highlightStart < item.highlightEnd,
              item.highlightEnd <= scalars.count else { return text }
        let lower = scalars.index(scalars.startIndex, offsetBy: item.highlightStart)
        let upper = scalars.index(scalars.startIndex, offsetBy: item.highlightEnd)
        text[lower..<upper].inlinePresentationIntent = .stronglyEmphasized
        return text
    }
}
