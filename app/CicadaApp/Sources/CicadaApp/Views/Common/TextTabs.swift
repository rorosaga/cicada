import SwiftUI

/// One text tab: a label and its count, in tabular figures. `id == nil` is "All".
struct TextTab<ID: Hashable>: Identifiable {
    let id: ID?
    let label: String
    var count: Int? = nil
    /// A service's real mark before the label (DR-52), for tabs that name services — the export walkthrough's
    /// Claude · ChatGPT · Gemini, which drew its own selected pill until round 3 (2026-10-20).
    var mark: AnyView? = nil
}

/// DR-45 — tabs are single-select; tapping the active one returns to All.
enum TextTabSelection {
    static func next<ID: Hashable>(tapping tapped: ID?, current: ID?) -> ID? {
        tapped == current ? nil : tapped
    }
    /// VoiceOver hears the count with the label (DR-69), grouped in the reader's locale
    /// like every other count in the window (R-S18).
    static func accessibilityLabel(label: String, count: Int?) -> String {
        count.map { "\(label), \(UsageFormat.count($0))" } ?? label
    }
    /// "Project · 42" — the narrow form's tooltip and the menu's item (R-DL25).
    static func menuLabel(label: String, count: Int?) -> String {
        count.map { "\(label) · \(UsageFormat.count($0))" } ?? label
    }
}

/// Text tabs with counts (DR-45) — "All 6 · Decay 1 · Conflict 2 …".
///
/// - 26 pt tall with 9 pt padding, in 12 medium.
/// - Active: `bgSelected` + `textPrimary`, its count in `textTertiaryOnFill`.
/// - Inactive: `textTertiary` with no fill. Hover: `bgHover` + `textSecondary`.
/// - No kind dots, never the accent (SelectionTintLintTests).
/// - A tab switch is instant (DR-61).
///
/// It replaces joined segmented bars, underline tabs and filter capsules on list pages; the
/// native segmented control remains inside Settings forms only. Each list page adopts it in its
/// own DS track (R-DS27).
struct TextTabs<ID: Hashable>: View {
    static var height: CGFloat { 26 }
    static var horizontalPadding: CGFloat { 9 }

    let tabs: [TextTab<ID>]
    @Binding var selection: ID?
    /// R-DL25 — false in `AdaptiveTextTabs`' narrow form: each count moves to its tab's `.help`.
    var showsCounts = true

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(2)) {
            ForEach(Array(tabs.enumerated()), id: \.offset) { _, tab in
                TextTabButton(tab: tab, isActive: tab.id == selection, showsCount: showsCounts) {
                    selection = TextTabSelection.next(tapping: tab.id, current: selection)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }
}

private struct TextTabButton<ID: Hashable>: View {
    let tab: TextTab<ID>
    let isActive: Bool
    let showsCount: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(5)) {
                if let mark = tab.mark { mark.accessibilityHidden(true) }
                Text(tab.label)
                if showsCount, let count = tab.count {
                    Text(UsageFormat.count(count))
                        .monospacedDigit()
                        .foregroundStyle(isActive ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                }
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(isActive ? CicadaTheme.textPrimary : (hovering ? CicadaTheme.textSecondary : CicadaTheme.textTertiary))
            .padding(.horizontal, CicadaTheme.scaled(TextTabs<ID>.horizontalPadding))
            .frame(height: CicadaTheme.scaled(TextTabs<ID>.height))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(isActive ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(TextTabSelection.accessibilityLabel(label: tab.label, count: tab.count))
        .accessibilityAddTraits(isActive ? [.isSelected] : [])
        .help(showsCount ? "" : TextTabSelection.menuLabel(label: tab.label, count: tab.count))
    }
}

/// R-DL25 (DR-45) — tabs that give way before they would overflow the eyebrow row: with counts, then without (each
/// count moves to its tab's `.help`, the mock's narrow state), then one menu naming the active tab. Clusters can show
/// twelve tabs; at 1200 pt and 1.4× they do not fit, and a clipped tab is a tab nobody can reach.
struct AdaptiveTextTabs<ID: Hashable>: View {
    let tabs: [TextTab<ID>]
    @Binding var selection: ID?
    /// The menu's accessibility name ("Type", "Kind").
    let menuTitle: String

    var body: some View {
        ViewThatFits(in: .horizontal) {
            TextTabs(tabs: tabs, selection: $selection)
            TextTabs(tabs: tabs, selection: $selection, showsCounts: false)
            Menu {
                ForEach(Array(tabs.enumerated()), id: \.offset) { _, tab in
                    Button {
                        selection = tab.id
                    } label: {
                        if tab.id == selection {
                            Label(TextTabSelection.menuLabel(label: tab.label, count: tab.count), systemImage: "checkmark")
                        } else {
                            Text(TextTabSelection.menuLabel(label: tab.label, count: tab.count))
                        }
                    }
                }
            } label: {
                Text(tabs.first { $0.id == selection }?.label ?? tabs.first?.label ?? "")
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .accessibilityLabel(menuTitle)
        }
    }
}

/// The owner's ruling for tabs that do not fit (2026-10-16, the Inbox's kinds at 1200 pt with the Reader open, and at
/// 1100): every tab with its count while they all fit; otherwise **All and the selected tab always stay visible**, and
/// the rest move into one "More" menu that lists each with its count. A label is never truncated (DR-45).
///
/// Unlike `AdaptiveTextTabs` (counts first, then one menu for everything), the active filter never hides behind a
/// menu, and the way back to All is always one click.
struct OverflowTextTabs<ID: Hashable>: View {
    let tabs: [TextTab<ID>]
    @Binding var selection: ID?
    /// What the menu reads to VoiceOver ("More kinds").
    var moreAccessibilityLabel: String = Copy.Lists.moreTabs

    var body: some View {
        ViewThatFits(in: .horizontal) {
            TextTabs(tabs: tabs, selection: $selection)
            HStack(spacing: CicadaTheme.scaled(2)) {
                TextTabs(tabs: OverflowTabs.pinned(tabs, selection: selection), selection: $selection)
                OverflowMoreMenu(tabs: OverflowTabs.folded(tabs, selection: selection), selection: $selection,
                                 accessibilityLabel: moreAccessibilityLabel)
            }
        }
    }
}

/// The split, pure (`TextTabsTests`): which tabs stay on the row and which fold into More.
enum OverflowTabs {
    /// All (the `nil` tab), then the selected tab when it is not All — in the row's own order.
    static func pinned<ID: Hashable>(_ tabs: [TextTab<ID>], selection: ID?) -> [TextTab<ID>] {
        tabs.filter { $0.id == nil || ($0.id != nil && $0.id == selection) }
    }

    /// Every other tab, in order.
    static func folded<ID: Hashable>(_ tabs: [TextTab<ID>], selection: ID?) -> [TextTab<ID>] {
        tabs.filter { $0.id != nil && $0.id != selection }
    }
}

/// "More ⌄" — drawn as an inactive text tab (12 medium, `textTertiary`, 26 pt), so the row reads as one row of tabs.
/// Its items carry their counts ("Possible duplicate · 2"); picking one selects it, and it joins the row.
private struct OverflowMoreMenu<ID: Hashable>: View {
    let tabs: [TextTab<ID>]
    @Binding var selection: ID?
    let accessibilityLabel: String
    @State private var hovering = false

    var body: some View {
        if !tabs.isEmpty {
            Menu {
                ForEach(Array(tabs.enumerated()), id: \.offset) { _, tab in
                    Button(TextTabSelection.menuLabel(label: tab.label, count: tab.count)) { selection = tab.id }
                }
            } label: {
                // One `Text` with the chevron inline: a `Menu` label lays an HStack's image out first ("⌄ More").
                (Text(Copy.Lists.more) + Text(verbatim: " ")
                    + Text(Image(systemName: "chevron.down")).font(CicadaTheme.font(size: 9, weight: .semibold)))
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(hovering ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.scaled(TextTabs<ID>.horizontalPadding))
                .frame(height: CicadaTheme.scaled(TextTabs<ID>.height))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                    .fill(hovering ? CicadaTheme.bgHover : Color.clear))
                .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .onHover { hovering = $0 }
            .help(tabs.map { TextTabSelection.menuLabel(label: $0.label, count: $0.count) }.joined(separator: ", "))
            .accessibilityLabel(accessibilityLabel)
        }
    }
}
