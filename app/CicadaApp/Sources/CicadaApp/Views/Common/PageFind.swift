import SwiftUI

/// DR-46 — a page's in-page find, opened with ⌘F or the eyebrow's magnifier (§10: Clusters and the Feed). While the
/// row is closed the PAGE publishes ⌘F (`publishesPageFind`) and opens it; once open the field publishes its own and
/// takes focus — never two publishers at once (R-SU10). The row closes when the field loses focus with nothing typed.
struct PageFindButton: View {
    @Binding var isOpen: Bool

    var body: some View {
        IconButton(systemName: "magnifyingglass", help: Copy.Lists.findHelp) { isOpen.toggle() }
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(isOpen ? CicadaTheme.bgSelected : Color.clear))
            .accessibilityAddTraits(isOpen ? .isSelected : [])
    }
}

struct PageFindRow: View {
    @Binding var text: String
    @Binding var isOpen: Bool
    let prompt: String

    var body: some View {
        CicadaSearchField(text: $text, prompt: prompt, autofocus: true, onFocusChange: { focused in
            if !focused && text.trimmingCharacters(in: .whitespaces).isEmpty { isOpen = false }
        })
    }
}
