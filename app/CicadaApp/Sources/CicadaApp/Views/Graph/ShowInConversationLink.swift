import SwiftUI

/// History's "Show in conversation ›" (R-DG24): a link (DR-5 #5) that opens the Reader on the one conversation a
/// commit consolidated, or today's chooser when there are several, or none in this bank (Resume may still work).
/// It replaced the "from conversation" button, which always opened the chooser.
struct ShowInConversationLink: View {
    let sessionIds: [String]
    let openEpisode: [String: String]
    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @State private var choosing = false

    var body: some View {
        switch HistoryConversation.action(sessions: sessionIds, openEpisode: openEpisode) {
        case .none:
            EmptyView()
        case .open(let episode):
            link { router?.open(ReaderTarget(episode: episode)) }
        case .choose:
            link { choosing = true }
                .popover(isPresented: $choosing, arrowEdge: .bottom) {
                    ConversationPopover(sessionIds: sessionIds, openEpisode: openEpisode)
                }
        }
    }

    private func link(_ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(3)) {
                Text(Copy.Graph.showInConversation)
                Image(systemName: "chevron.right").font(CicadaTheme.font(size: 9, weight: .semibold))
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(CicadaTheme.accentText)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Graph.showInConversationHelp)
    }
}
