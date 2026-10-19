import SwiftUI

/// The Sleep page's list row (DESIGN §3.4, DR-45): the four tabs with their counts in tabular `textTertiary`, then the
/// selected list's tools — Saved's View menu, find (⌘F) on a list of saved items, and the one-shot import's `+` (⌘N,
/// the Feed's door, R-DL14). With nothing open it is the sticky header under the room; with an item open it rides the
/// columns' eyebrow. A tab switch never animates (DR-60): the caller runs it in `Instant.run`.
struct SleepTabRow: View {
    let tabs: [TextTab<SleepTab>]
    let selected: SleepTab
    let select: (SleepTab) -> Void
    @Binding var findOpen: Bool
    let onAdd: () -> Void
    /// Only the sticky row names nothing on its left; beside an open item the eyebrow says where the list is.
    var showsTools = true

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            // One tab is always on: tapping the active one keeps it, and changes nothing (a list is not a filter with an
            // "All", and re-selecting it must not close find or the open item).
            TextTabs(tabs: tabs, selection: Binding(get: { selected }, set: { tab in
                if let tab, tab != selected { select(tab) }
            }))
                .accessibilityLabel(Copy.SleepTabs.tabsLabel)
            if showsTools {
                Spacer(minLength: CicadaTheme.spacingSM)
                tools
            }
        }
    }

    @ViewBuilder
    var tools: some View {
        if selected == .saved {
            SavedViewMenu()
        }
        if selected.hasFind {
            PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
        }
        // R-DL14 — the one-shot import's door (G126), a plain icon, and ⌘N's only home. The page draws one row at a
        // time (the sticky one with nothing open, the eyebrow's beside an item), so ⌘N has one publisher.
        IconButton(systemName: "plus", help: Copy.Lists.addSourceShortcut,
                   accessibilityLabel: Copy.addASource,
                   shortcut: KeyboardShortcut("n", modifiers: .command), action: onAdd)
    }

    /// The tabs on screen with their counts; Past reads carries none (it is not a pile). Waiting carries none either
    /// while the room's headline above it already says the same number (`roomLead`, say it once).
    static func tabs(_ shown: [SleepTab], waiting: Int, saved: Int, videos: Int,
                     roomLead: SentenceLine? = nil) -> [TextTab<SleepTab>] {
        let waitingCount = leadSays(waiting, roomLead) ? nil : waiting
        return shown.map { tab in
            switch tab {
            case .waiting: TextTab(id: tab, label: tab.label, count: waitingCount)
            case .saved: TextTab(id: tab, label: tab.label, count: saved)
            case .videos: TextTab(id: tab, label: tab.label, count: videos)
            case .pastReads: TextTab(id: tab, label: tab.label)
            }
        }
    }
}

extension SleepTabRow {
    /// Whether the room's lead names exactly this count as its numeral ("23 to read." — not "Reading 14 of 25.").
    static func leadSays(_ waiting: Int, _ lead: SentenceLine?) -> Bool {
        guard waiting > 0, let numeral = lead?.numeral else { return false }
        return numeral.filter(\.isNumber) == String(waiting)
    }
}

/// The Saved tab's View menu (DESIGN §3.4): the Feed's sort (Relevance · Recent, one always on — R-DL13) and its kind
/// filter (All and each kind with its count, DR-45) in one menu, so Saved never grows a second tab row (DR-38).
struct SavedViewMenu: View {
    @Environment(FeedViewModel.self) private var viewModel

    var body: some View {
        Menu {
            Picker(Copy.SleepTabs.sortTitle, selection: Binding(get: { viewModel.sort }, set: { viewModel.sort = $0 })) {
                ForEach(FeedViewModel.SortMode.allCases) { mode in Text(mode.label).tag(mode) }
            }
            .pickerStyle(.inline)
            Picker(Copy.SleepTabs.kindTitle,
                   selection: Binding(get: { viewModel.kind }, set: { kind in Instant.run { viewModel.setKind(kind) } })) {
                ForEach(Array(viewModel.kindTabs.enumerated()), id: \.offset) { _, tab in
                    Text(TextTabSelection.menuLabel(label: tab.label, count: tab.count)).tag(tab.id)
                }
            }
            .pickerStyle(.inline)
        } label: {
            Text(Self.label(kind: viewModel.kind))
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(viewModel.kind == nil ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(Copy.Lists.sortFeed)
        .accessibilityLabel(Copy.SleepTabs.view)
    }

    /// "View", or "View · Papers" while a kind narrows the list — the filter is never invisible.
    static func label(kind: FeedKind?) -> String {
        Eyebrow.text(Copy.SleepTabs.view, kind?.label ?? "")
    }
}
