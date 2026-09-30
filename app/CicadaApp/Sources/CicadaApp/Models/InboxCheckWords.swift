import Foundation

/// G61 S3 — what an agent found at a source for an inbox question, in words, for the question's card. SHADOW: a finding
/// is a report. It settles nothing, highlights no option, moves nothing in the list and never answers for the person —
/// the card says so plainly. Every sentence is about what the agent SAID it saw, never that Cicada confirmed it, and none
/// names a provider or a model (the server sends a harness label, which this never shows).
enum InboxCheckWords {
    struct Line: Equatable {
        let heading: String
        /// The page's words as the agent reported them, when the server sent one.
        let quote: String?
        let result: String
    }

    /// Newest first, at most two.
    static func lines(_ item: InboxItem, locale: Locale = .autoupdatingCurrent) -> [Line] {
        item.checks.sorted { $0.at > $1.at }.prefix(2).map { line($0, options: item.options, locale: locale) }
    }

    /// The caption under the reports: who reported, by the newest finding's kind (the same word as its heading).
    static func caption(_ item: InboxItem) -> String {
        item.checks.max { $0.at < $1.at }?.checkerKind == "remote" ? Copy.Inbox.checkCaptionApp : Copy.Inbox.checkCaption
    }

    static func line(_ finding: InboxCheckFinding, options: [InboxOption], locale: Locale = .autoupdatingCurrent) -> Line {
        let who = finding.checkerKind == "remote" ? Copy.Inbox.checkedByApp : Copy.Inbox.checkedByAgent
        let day = EntityDates.shortDay(finding.at, locale: locale)
        let host = finding.host.isEmpty ? Copy.Inbox.checkedASource : finding.host
        let heading = day.map { Copy.Inbox.checkedHeading(who: who, host: host, day: $0) }
            ?? Copy.Inbox.checkedHeadingNoDay(who: who, host: host)
        let quote = finding.quote?.trimmingCharacters(in: .whitespacesAndNewlines)
        return Line(heading: heading, quote: (quote?.isEmpty ?? true) ? nil : quote, result: result(finding, options: options))
    }

    static func result(_ finding: InboxCheckFinding, options: [InboxOption]) -> String {
        switch finding.outcome {
        case "supports":
            let label = options.first { $0.key == finding.optionKey }?.label
            return label.map(Copy.Inbox.checkSupports) ?? Copy.Inbox.checkSupportsAnOption
        case "proposes":
            let value = finding.proposedValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return value.isEmpty ? Copy.Inbox.checkProposesAnother : Copy.Inbox.checkProposes(value)
        case "contradicts_all": return Copy.Inbox.checkContradicts
        default: return Copy.Inbox.checkUnclear
        }
    }
}
