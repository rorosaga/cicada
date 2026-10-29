import SwiftUI

/// Ruling 48 part 5 (part B, 2026-10-29; mock 01's slot 2): "In short" — the 2–3 sentences Sleep wrote for a long page
/// the person talks about often (`page_blocks.summary`). A `Sleep` `Tag` with its day says who wrote it (DR-44, DR-77's
/// tag), the basis line says why the page has one; it is never editable — Sleep rewrites it when the article changes.
/// Part A's page layout owns where it sits; this is the block itself.
struct InShortBlock: View {
    let summary: InShort

    private var day: String? {
        guard let raw = summary.writtenAt, !raw.isEmpty else { return nil }
        return EntityDates.shortDay(String(raw.prefix(10))) ?? raw
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SectionLabel(Copy.Graph.inShort)
                Tag(text: Copy.Graph.inShortTag(day))
            }
            Text(summary.text)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineSpacing(CicadaTheme.scaled(3))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            if let n = summary.conversations, n > 0 {
                Text(Copy.Graph.inShortBasis(n))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .help(Copy.Graph.inShortHelp)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("entity-in-short")
    }
}
