import SwiftUI

/// One source's page (G124). A harness shows its conversations; every other
/// kind shows its channel state, folder counts and items. Back is a chevron
/// and ⌘[ (R15) — the same key the entity card uses on the Graph tab, which
/// is never mounted at the same time as this view.
///
/// The header (Track D) leads with the source's own mark and one honest
/// sentence of what Cicada reads from it (`SourceBlurb`) instead of the raw
/// count line — the counts move to the queue strip's "consolidated so far"
/// line (added in the next task).
struct SourceDetailView: View {
    let source: SourceOverview
    let onBack: () -> Void
    var onSelectEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: source.label, subtitle: SourceBlurb.text(for: source),
                       leading: AnyView(OriginMark(origin: source.mark, size: 28))) {
                Button(action: onBack) {
                    Label("Sources", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all sources (⌘[)")
                .accessibilityLabel("Back to all sources")
            }
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
    }
}
