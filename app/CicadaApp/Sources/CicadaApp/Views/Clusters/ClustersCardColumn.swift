import SwiftUI

/// §10 / R-DL10 — the entity card as Clusters' detail column. It hosts DS-3a's `EntityDetailCard` as it is — its
/// internals are DS-3a's, and editing them here would fork it — in the `.card` style (R-DG13): the column frames it in
/// its gutter like the Inbox's focus card, so the Graph's `.column` (its own edge and 28-unit inset) is not this host's.
/// It keeps the "go deeper, then come back" trail this page always kept for itself (G108 bug 3,
/// `TopicDetailNavigation`), moved from the retired `TopicDetailView`. The card's Back ⌘[ is the card's; its Esc is the
/// page's, through DS-3a's `onEscape` seam (DR-28), so focus inside the card still closes the rightmost column. The
/// column adds Close × and, when DR-27 hides the list, "‹ N entities".
struct ClustersCardColumn: View {
    let entity: Entity
    let gutter: CGFloat
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(GraphViewModel.self) private var graphVM
    @State private var fullEntity: Entity?
    @State private var nav = TopicDetailNavigation<Entity>()
    /// The one in-flight full-body fetch; cancelled on every new `navigate`/`goBackEntity`. `nav`'s token is the
    /// backstop for a cancellation that arrives too late to stop the response (PR #29 round 2).
    @State private var navTask: Task<Void, Never>?

    private var displayEntity: Entity { nav.pushed ?? fullEntity ?? entity }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let n = hiddenListCount {
                    TextButton(title: Copy.Lists.entitiesBack(n), help: Copy.Lists.showList, action: onShowList)
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                Spacer(minLength: 0)
                IconButton(systemName: "xmark", help: Copy.Lists.closeCard, action: onClose)
            }
            // One card identity per entity (the graph overlay's rule): a wikilink push swaps the shown entity.
            EntityDetailCard(entity: displayEntity, showsCloseButton: false, navigation: cardNavigation, style: .card,
                             onEscape: onEscape)
                .id(displayEntity.id)
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        .padding(.bottom, CicadaTheme.spacingLG)
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: entity.id) {
            fullEntity = try? await APIClient.shared.fetchEntity(id: entity.id)
        }
    }

    private func navigate(to id: String) {
        navTask?.cancel()
        // An instant placeholder from the graph's stub, then the full body.
        let token = nav.navigate(from: displayEntity, toStub: graphVM.entities.first(where: { $0.id == id }))
        navTask = Task {
            guard let full = try? await APIClient.shared.fetchEntity(id: id) else { return }
            nav.apply(full, token: token)
        }
    }

    private func goBackEntity() {
        navTask?.cancel()
        nav.goBack(rootID: entity.id)
    }

    private var cardNavigation: EntityCardNavigation {
        EntityCardNavigation(canGoBack: nav.canGoBack, backTargetName: nav.backTarget?.name,
                             goBack: goBackEntity, navigate: navigate)
    }
}
