import SwiftUI

/// The one section label (DR-20, DR-47): sentence case, `labelFont` (11 medium), `textTertiary`.
///
/// It replaces ~27 hand-spelled labels in 10 pt semibold MONOSPACED capitals with 1.2 tracking
/// — each the loudest thing in its card, over content that should lead (P1, P-a). It says
/// nothing about case: the words arrive in sentence case, and SectionLabelLintTests fails a
/// caps literal or an `.uppercased()` at the call site.
struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(CicadaTheme.labelFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .accessibilityAddTraits(.isHeader)
    }
}
