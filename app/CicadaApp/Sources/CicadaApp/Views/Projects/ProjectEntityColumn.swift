import SwiftUI

/// R-PP17 — an entity's card as the Projects page's third column, the Reader's slot: DS-3a's `EntityDetailCard` as it
/// is, in its `.column` style (the card draws its own column edge), with the "go deeper, then come back" trail Clusters
/// keeps (`TopicDetailNavigation`, G108 bug 3) so a wikilink inside it never moves the Graph's selection. A project's
/// card adds "Open project ›", which opens it on this page.
struct ProjectEntityColumn: View {
    let entityId: String
    let openProject: (String) -> Void
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(GraphViewModel.self) private var graphVM
    @State private var fullEntity: Entity?
    @State private var nav = TopicDetailNavigation<Entity>()
    @State private var navTask: Task<Void, Never>?

    private var displayEntity: Entity? { nav.pushed ?? fullEntity ?? graphVM.entities.first { $0.id == entityId } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let entity = displayEntity {
                if entity.type == .project {
                    InlineLink(title: Copy.Projects.openProject, help: Copy.Projects.openHelp) { openProject(entity.id) }
                        .padding(.horizontal, CicadaTheme.scaled(28))
                        .padding(.top, CicadaTheme.spacingSM)
                }
                EntityDetailCard(entity: entity, showsCloseButton: true, navigation: cardNavigation, style: .column,
                                 onClose: onClose, onEscape: onEscape)
                    .id(entity.id)
            } else {
                ListSkeleton(message: Copy.Projects.readingCard).padding(CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .task(id: entityId) { fullEntity = try? await APIClient.shared.fetchEntity(id: entityId) }
    }

    private func navigate(to id: String) {
        navTask?.cancel()
        guard let from = displayEntity else { return }
        let token = nav.navigate(from: from, toStub: graphVM.entities.first { $0.id == id })
        navTask = Task {
            guard let full = try? await APIClient.shared.fetchEntity(id: id) else { return }
            nav.apply(full, token: token)
        }
    }

    private func goBack() {
        navTask?.cancel()
        nav.goBack(rootID: entityId)
    }

    private var cardNavigation: EntityCardNavigation {
        EntityCardNavigation(canGoBack: nav.canGoBack, backTargetName: nav.backTarget?.name, goBack: goBack,
                             navigate: navigate)
    }
}
