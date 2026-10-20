import SwiftUI

/// DR-39 — a section of the entity card that waits for a click: a chevron and the section's name, a few words of what
/// is inside while closed, and the content only once open. The content is not built while closed, so whatever it reads
/// (`.task` inside it) is read when asked (owner 2026-10-09: the card opens on the page; claims, provenance,
/// connections, sources and details load on request). Each viewer's choice is remembered per section.
struct CardDisclosure<Content: View>: View {
    let title: String
    /// Words shown beside a closed section ("· 4,770"); nil says nothing.
    var summary: String? = nil
    @Binding var isOpen: Bool
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            DisclosureHeader(title: title, summary: summary, isOpen: isOpen) { isOpen.toggle() }
            if isOpen { content() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The card's remembered disclosures (DR-39): the `@AppStorage` keys, one per section, each closed until its viewer
/// opens it. Details keeps its own key (`DetailsWords.openKey`).
enum CardSections {
    static let beliefsKey = "cicada.card.beliefsOpen"
    static let provenanceKey = "cicada.card.provenanceOpen"
    static let connectionsKey = "cicada.card.connectionsOpen"
    /// A page with no looks yet: the Looks section's ways to add one (owner 2026-10-20).
    static let looksKey = "cicada.card.looksOpen"
}

/// A section reading its data, said in words beside a small spinner (DR-32's rule: never a blank).
struct SectionLoading: View {
    let text: String

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ProgressView().controlSize(.small)
            Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
