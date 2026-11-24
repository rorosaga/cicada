import SwiftUI

/// The Sleep page's list row (DESIGN §3.4, DR-45): the four tabs with their counts in tabular `textTertiary`, then the
/// selected list's tools — Saved's View menu and find (⌘F) on a list of saved items. With nothing open it is the sticky
/// header under the room; with an item open it rides the columns' eyebrow. A tab switch never animates (DR-60): the
/// caller runs it in `Instant.run`. Its Add button is gone (owner 2026-11-23: "I don't get why there is an add"): it
/// only opened the Sources page, which the rail already opens and which keeps its own Add.
struct SleepTabRow: View {
    let tabs: [TextTab<SleepTab>]
    let selected: SleepTab
    let select: (SleepTab) -> Void
    @Binding var findOpen: Bool
    /// Only the sticky row names nothing on its left; beside an open item the eyebrow says where the list is.
    var showsTools = true

    var body: some View {
        let split = Self.fold(tabs, selected: selected)
        HStack(spacing: CicadaTheme.spacingXS) {
            // One tab is always on: tapping the active one keeps it, and changes nothing (a list is not a filter with an
            // "All", and re-selecting it must not close find or the open item).
            TextTabs(tabs: split.inline, selection: Binding(get: { selected }, set: { tab in
                if let tab, tab != selected { select(tab) }
            }), large: true)
                .accessibilityLabel(Copy.SleepTabs.tabsLabel)
            SleepMoreMenu(tabs: split.folded) { select($0) }
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
    }

    /// The two Sleep lists stay on the row; Saved and Videos fold into the `⋯` menu, and one of them is on the row for
    /// as long as it is the selected list. Pure (`SleepTabRowTests`): the row's order is kept.
    static func fold(_ tabs: [TextTab<SleepTab>], selected: SleepTab) -> (inline: [TextTab<SleepTab>], folded: [TextTab<SleepTab>]) {
        func stays(_ tab: TextTab<SleepTab>) -> Bool {
            guard let id = tab.id else { return true }
            return id.isSleepList || id == selected
        }
        return (tabs.filter(stays), tabs.filter { !stays($0) })
    }

    /// The tabs on screen with their counts; Past sleeps carries none (it is not a pile).
    static func tabs(_ shown: [SleepTab], waiting: Int, saved: Int, videos: Int) -> [TextTab<SleepTab>] {
        shown.map { tab in
            switch tab {
            case .waiting: TextTab(id: tab, label: tab.label, count: waiting)
            case .saved: TextTab(id: tab, label: tab.label, count: saved)
            case .videos: TextTab(id: tab, label: tab.label, count: videos)
            case .pastReads: TextTab(id: tab, label: tab.label)
            }
        }
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

/// "⋯" — Saved and Videos, with their counts. Drawn as an inactive text tab (the row's 26 pt, `textTertiary`), so the
/// row reads as one row; icon-only, so it says what it holds in `.help` and to VoiceOver. Nothing when nothing folds.
private struct SleepMoreMenu: View {
    let tabs: [TextTab<SleepTab>]
    let select: (SleepTab) -> Void
    @State private var hovering = false

    var body: some View {
        if !tabs.isEmpty {
            Menu {
                ForEach(Array(tabs.enumerated()), id: \.offset) { _, tab in
                    if let id = tab.id {
                        Button(TextTabSelection.menuLabel(label: tab.label, count: tab.count)) { select(id) }
                    }
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(CicadaTheme.font(size: 14, weight: .semibold))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    // The page's own (large) tabs: 12 pt of padding in a 30 pt pill, so the menu stands in the row.
                    .padding(.horizontal, CicadaTheme.scaled(12))
                    .frame(height: CicadaTheme.scaled(30))
                    .rowHoverFill(hovering: hovering)
                    .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .onHover { hovering = $0 }
            .help(tabs.map { TextTabSelection.menuLabel(label: $0.label, count: $0.count) }.joined(separator: ", "))
            .accessibilityLabel(Copy.SleepPage.moreAccessibility)
        }
    }
}
