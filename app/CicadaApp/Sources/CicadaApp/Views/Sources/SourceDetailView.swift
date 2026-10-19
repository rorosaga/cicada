import SwiftUI

/// One source, as the Sources page's detail column (G124; R-DL19). Sources v4 (owner 2026-10-19): one header that says
/// what the source is, once (`SourceDetailHead`: the mark, the name, one line, its state and last sync with Sync now,
/// and "Consolidate now · N waiting" only while something waits), then the list — a harness's conversations, a saved
/// source's saved things, every other source's items. Close × and ⌘[ return to all sources (R15's key, kept); "‹ N
/// sources" leads the head when DR-27 hid the list.
struct SourceDetailView: View {
    let source: SourceOverview
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store

    /// `source` is a snapshot captured at navigation time (`SourcesPageView`'s `route` holds it in a plain `let`), so
    /// after a sync or a Consolidate run its counts are stale. Re-resolve by id on every render, falling back to the
    /// snapshot when the row has aged out of the overview.
    private var live: SourceOverview {
        store.sourcesOverview.value?.first(where: { $0.id == source.id }) ?? source
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SourceDetailHead(source: live, hiddenListCount: hiddenListCount, onShowList: onShowList, onClose: onClose)
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}
