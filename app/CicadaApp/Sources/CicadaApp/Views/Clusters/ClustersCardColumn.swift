import SwiftUI

/// §10 / R-DL10 — the entity card as Clusters' detail column. It hosts DS-3a's `EntityDetailCard` as it is — its
/// internals are DS-3a's, and editing them here would fork it — in the `.card` style (R-DG13): the column frames it in
/// its gutter like the Inbox's focus card, so the Graph's `.column` (its own edge and 28-unit inset) is not this host's.
/// It keeps the "go deeper, then come back" trail this page always kept for itself (G108 bug 3,
/// `TopicDetailNavigation`), moved from the retired `TopicDetailView`. The card's Back ⌘[ is the card's; its Esc is the
/// page's, through DS-3a's `onEscape` seam (DR-28), so focus inside the card still closes the rightmost column. The
/// card's header carries Close × (the column's `onClose`), and the column adds "‹ N entities" when DR-27 hides the list.
struct ClustersCardColumn: View {
    let entity: Entity
    let gutter: CGFloat
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(GraphViewModel.self) private var graphVM
    @Environment(Store.self) private var store
    @State private var fullEntity: Entity?
    @State private var nav = TopicDetailNavigation<Entity>()
    /// The one in-flight full-body fetch; cancelled on every new `navigate`/`goBackEntity`. `nav`'s token is the
    /// backstop for a cancellation that arrives too late to stop the response (PR #29 round 2).
    @State private var navTask: Task<Void, Never>?

    /// The pushed page, else this page as the graph last read it in full (a write on the page re-reads it there,
    /// `GraphViewModel.reloadEntity`), else the body this column read, else the list's stub.
    private var displayEntity: Entity {
        nav.pushed ?? graphVM.entities.first(where: { $0.id == entity.id && !$0.isStub }) ?? fullEntity ?? entity
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let n = hiddenListCount {
                TextButton(title: Copy.Lists.entitiesBack(n), help: Copy.Lists.showList, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            // One card identity per entity (the graph overlay's rule): a wikilink push swaps the shown entity.
            // Close × sits in the card's own header line (§5.3's header anatomy; QA 2026-10-16: it floated above the
            // card's top-right corner, outside it).
            EntityDetailCard(entity: displayEntity, showsCloseButton: true, navigation: cardNavigation, style: .card,
                             onClose: onClose, onEscape: onEscape)
                .id(displayEntity.id)
        }
        // Every card keeps the focus width: a person's opens on its page too, one column (owner 2026-10-09).
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        .padding(.bottom, CicadaTheme.spacingLG)
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: entity.id) {
            // Through the Store's memo, which the card reads too: one request when the column opens, not two.
            fullEntity = await store.entity(entity.id)
        }
    }

    private func navigate(to id: String) {
        navTask?.cancel()
        // An instant placeholder from the graph's stub, then the full body.
        let token = nav.navigate(from: displayEntity, toStub: graphVM.entities.first(where: { $0.id == id }))
        navTask = Task {
            guard let full = await store.entity(id) else { return }
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
