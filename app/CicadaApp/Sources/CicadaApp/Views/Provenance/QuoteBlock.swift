import SwiftUI

/// A quoted passage with its neighbourhood (design §1.3, §4.2): the words
/// before and after in a quiet colour, the cited words in the quote face
/// (New York italic, R-M3). One component for the hover preview, "Where this
/// came from", and anywhere else a sentence is shown as evidence.
///
/// The style carries the honesty rule (§4.9): an asserted span is WASHED, a
/// derived match is BOLD (found by name, not quoted), and a stale quote is
/// PLAIN — shown so the person has something to read, never highlighted as if
/// its offsets still held.
struct QuoteBlock: View {
    enum Style: Hashable { case wash, bold, plain }

    let before: String
    let span: String
    let after: String
    let kind: EvidenceKind
    /// "You said", "Claude Code replied", "Mentioned here"…
    let label: String?
    /// "Quoted by the contributor" / "Found by searching the conversation".
    let caption: String?
    let style: Style
    var lineLimit: Int? = 8

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            RoundedRectangle(cornerRadius: 1)
                .fill(EvidenceLabel.ruleColor(kind))
                .frame(width: 2)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Self.attributed(before: before, span: span, after: after, style: style))
                    .font(CicadaTheme.font(size: 12))
                    .lineLimit(lineLimit)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if label != nil || caption != nil {
                    Text([label, caption].compactMap { $0 }.joined(separator: " · "))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    /// The span in `quoteFont`; the neighbourhood in `textTertiary`. The wash
    /// is the accent `wash` (DR-18, R-DI11); the dandelion wash retired with
    /// the Reader's margin bar (DR-13).
    static func attributed(before: String, span: String, after: String, style: Style) -> AttributedString {
        var head = AttributedString(before)
        head.foregroundColor = CicadaTheme.textTertiary
        var middle = AttributedString(span)
        middle.font = CicadaTheme.quoteFont(size: 12)
        middle.foregroundColor = CicadaTheme.textPrimary
        switch style {
        case .wash: middle.backgroundColor = CicadaTheme.wash
        case .bold: middle.inlinePresentationIntent = .stronglyEmphasized
        case .plain: break
        }
        var tail = AttributedString(after)
        tail.foregroundColor = CicadaTheme.textTertiary
        return head + middle + tail
    }

    /// An excerpt with its first mention (offsets RELATIVE to the excerpt,
    /// the G115 inbox-cause shape `/provenance` reuses) split into the three
    /// parts; no mention → the whole excerpt as context, nothing emphasised.
    static func parts(excerpt: String, mentionOffsets: [[Int]]) -> (before: String, span: String, after: String) {
        let text = ScalarText(excerpt)
        guard let pair = mentionOffsets.first, pair.count == 2, pair[1] > pair[0], pair[0] >= 0,
              pair[1] <= text.count else { return (excerpt, "", "") }
        return (text.slice(0, pair[0]), text.slice(pair[0], pair[1]), text.slice(pair[1], text.count))
    }
}
