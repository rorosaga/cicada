import SwiftUI

/// Navigation is an icon rail, 56 pt wide (DR-22). It replaced the labelled
/// `NavigationSplitView` sidebar (R-DS13):
///
/// - a 56 pt column cannot sit under the full-width titlebar the command bar needs;
/// - `List` selection painted the accent, and DR-5 spends the accent on six things, none of
///   them navigation.
///
/// One view draws both widths — the rail, and the 208 pt labelled sidebar the titlebar toggle
/// and ⌃⌘S switch to (R-DS15) — so a page never has two drawings.
///
/// **State.** Inactive glyphs are `textTertiary`. The selected cell is `bgSelected` with a
/// `textPrimary` glyph: never the accent, never a filled symbol. A hover is `bgRailHover`. The
/// Inbox numeral is neutral: `bgBadge`, with a 2 pt `bgRail` knockout. Sleep shows a spinner
/// while a cycle runs.
///
/// **Keys.** ⌘1–8 are the cells' own shortcuts, in `AppTab.allCases` order (`RailItem`). A
/// switch is instant, pointer and key alike (DR-60/61).
///
/// **Tooltips.** Each cell names its page and shortcut ("Inbox ⌘6"). The first waits 450 ms and
/// the next opens at once (R-DS14). `.help` cannot be timed, so the bubble is SwiftUI; the
/// cell's accessibility label and hint are its text twin.
struct NavRail: View {
    @Binding var selectedTab: AppTab
    let labelled: Bool
    var inboxCount: Int
    var isSleeping: Bool
    var needsAttention: Bool

    @AppStorage(ThemeStore.defaultsKey) private var colorSchemeRaw: String = AppColorScheme.dark.rawValue
    @State private var tooltip = RailTooltipState()

    var body: some View {
        VStack(alignment: labelled ? .leading : .center, spacing: 0) {
            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(AppTab.allCases, id: \.self) { tab in cell(tab) }
            }
            Spacer(minLength: CicadaTheme.spacingLG)
            foot
        }
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.scaled(ShellMetrics.railInset))
        .padding(.bottom, CicadaTheme.spacingMD)
        .frame(width: ShellMetrics.navWidth(labelled: labelled))
        .frame(maxHeight: .infinity, alignment: .top)
        .background(CicadaTheme.bgRail)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.pages)
    }

    @ViewBuilder
    private func cell(_ tab: AppTab) -> some View {
        let count = tab == .inbox ? inboxCount : 0
        let busy = tab == .sleep && isSleeping
        let selected = selectedTab == tab
        Button { selectedTab = tab } label: {
            NavRailCell(tab: tab, labelled: labelled, selected: selected, badge: count, busy: busy)
        }
        .buttonStyle(.cicadaPlain)
        .keyboardShortcut(RailItem.key(for: tab), modifiers: .command)
        .accessibilityLabel(RailItem.accessibilityLabel(tab, count: count, busy: busy))
        .accessibilityHint(RailItem.shortcut(for: tab))
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .onHover { tooltip.hover(tab, inside: $0) }
        .overlay(alignment: .leading) {
            if !labelled, tooltip.shown == tab {
                RailTooltip(tab: tab, busy: busy)
                    .fixedSize()
                    .offset(x: CicadaTheme.scaled(ShellMetrics.railCell + ShellMetrics.railInset))
                    .allowsHitTesting(false)
            }
        }
    }

    /// The gear and the theme toggle: a column on the rail, a row in the labelled sidebar.
    private var foot: some View {
        let layout = labelled ? AnyLayout(HStackLayout(spacing: CicadaTheme.spacingXS))
                              : AnyLayout(VStackLayout(spacing: CicadaTheme.spacingXS))
        return layout {
            RailGear(needsAttention: needsAttention)
            RailThemeToggle(colorSchemeRaw: $colorSchemeRaw)
        }
    }
}

struct NavRailCell: View {
    let tab: AppTab
    let labelled: Bool
    let selected: Bool
    let badge: Int
    let busy: Bool
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var ink: Color { selected || hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary }
    private var fill: Color { selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgRailHover : Color.clear) }

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            glyph
            if labelled {
                Text(tab.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(ink)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if badge > 0 { RailBadge(count: badge, style: .inline) }
            }
        }
        .padding(.horizontal, labelled ? CicadaTheme.scaled(10) : 0)
        .frame(width: labelled ? nil : CicadaTheme.scaled(ShellMetrics.railCell),
               height: CicadaTheme.scaled(labelled ? ShellMetrics.sidebarRow : ShellMetrics.railCell))
        .frame(maxWidth: labelled ? .infinity : nil, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(fill))
        .overlay(alignment: .topTrailing) {
            if !labelled, badge > 0 {
                RailBadge(count: badge, style: .corner)
                    .padding(.top, CicadaTheme.scaled(3))
                    .padding(.trailing, CicadaTheme.scaled(2))
            }
        }
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }

    @ViewBuilder
    private var glyph: some View {
        let side = CicadaTheme.iconPoints(.rail)
        if busy {
            ProgressView().controlSize(.small).frame(width: side, height: side)
        } else {
            Image(systemName: tab.icon)
                .font(CicadaTheme.icon(.rail))
                .foregroundStyle(ink)
                .frame(width: side, height: side)
                .iconHover(hovering: hovering)
        }
    }
}

/// The rail's pending numeral (DR-22, DR-51): the only badge in the app — tabular
/// `textPrimary` on a `bgBadge` capsule, knocked out of the rail by 2 pt.
struct RailBadge: View {
    enum Style { case corner, inline }
    let count: Int
    let style: Style

    var body: some View {
        let corner = style == .corner
        Text(UsageFormat.count(count))
            .font(corner ? CicadaTheme.badgeFont : CicadaTheme.font(size: 11, weight: .medium))
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.scaled(corner ? 3 : 5))
            .frame(minWidth: CicadaTheme.scaled(corner ? 14 : 18), minHeight: CicadaTheme.scaled(corner ? 14 : 18))
            .background(Capsule().fill(CicadaTheme.bgBadge))
            .background { if corner { Capsule().fill(CicadaTheme.bgRail).padding(-2) } }
            .accessibilityHidden(true)   // the cell's label already says "6 pending"
    }
}

/// A 36 pt foot cell (the rail's pitch, not IconButton's 28): the gear and the theme toggle
/// sit at the rail's own size so the foot lines up with the pages above it.
private struct RailFootGlyph: View {
    let systemName: String
    let hovering: Bool

    var body: some View {
        Image(systemName: systemName)
            .font(CicadaTheme.icon(.railFoot))
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            .iconHover(hovering: hovering)
            .frame(width: CicadaTheme.scaled(ShellMetrics.railCell), height: CicadaTheme.scaled(ShellMetrics.railCell))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgRailHover : Color.clear))
            .contentShape(Rectangle())
    }
}

/// The gear (⌘,) opens the Settings panel through the one door (R-DS22).
private struct RailGear: View {
    let needsAttention: Bool
    @State private var hovering = false
    @Environment(AppRouter.self) private var router

    var body: some View {
        Button { router.openSettings() } label: {
            RailFootGlyph(systemName: "gearshape", hovering: hovering)
                .overlay(alignment: .topTrailing) {
                    if needsAttention {
                        Circle().fill(CicadaTheme.warning)
                            .frame(width: 6, height: 6)
                            .background(Circle().fill(CicadaTheme.bgRail).padding(-2))
                            .padding(CicadaTheme.scaled(8))
                    }
                }
        }
        .buttonStyle(.cicadaPlain)
        .help(needsAttention ? Copy.settingsAttentionHelp : Copy.settingsHelp)
        .accessibilityLabel(needsAttention ? Copy.settingsAttentionLabel : Copy.settings)
        .onHover { hovering = $0 }
    }
}

/// Sun/moon (DR-22): an explicit Light or Dark — flipping the glyph means "not this one", which
/// a `system` preference cannot say. The glyph swaps with `.symbolEffect(.replace)`.
private struct RailThemeToggle: View {
    @Binding var colorSchemeRaw: String
    @State private var hovering = false

    var body: some View {
        let dark = CicadaTheme.mode == .dark
        Button {
            colorSchemeRaw = (dark ? AppearancePreference.light : AppearancePreference.dark).rawValue
        } label: {
            RailFootGlyph(systemName: dark ? "moon" : "sun.max", hovering: hovering)
                .contentTransition(.symbolEffect(.replace))
        }
        .buttonStyle(.cicadaPlain)
        .help(dark ? Copy.switchToLight : Copy.switchToDark)
        .accessibilityLabel(dark ? Copy.switchToLight : Copy.switchToDark)
        .onHover { hovering = $0 }
    }
}

/// The tooltip bubble: `bgMenu`, the floating ring, one line.
private struct RailTooltip: View {
    let tab: AppTab
    let busy: Bool

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(RailItem.tooltipTitle(tab, busy: busy)).foregroundStyle(CicadaTheme.textPrimary)
            Text(RailItem.shortcut(for: tab)).foregroundStyle(CicadaTheme.textTertiary)
        }
        .font(CicadaTheme.metaMediumFont)
        .padding(.horizontal, CicadaTheme.scaled(9))
        .frame(height: CicadaTheme.scaled(26))
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .accessibilityHidden(true)
    }
}

/// R-DS14 — which tooltip shows. Enter and exit can arrive in either order when the pointer
/// crosses from one cell to the next, so an exit only hides the tooltip it owns.
@Observable
@MainActor
final class RailTooltipState {
    private(set) var shown: AppTab?
    @ObservationIgnored private var lastHiddenAt: Date?
    @ObservationIgnored private var pending: Task<Void, Never>?

    func hover(_ tab: AppTab, inside: Bool, now: Date = Date()) {
        pending?.cancel()
        guard inside else {
            if shown == tab { shown = nil; lastHiddenAt = now }
            return
        }
        let delay = RailTooltipTiming.delay(lastHiddenAt: lastHiddenAt, isShowing: shown != nil, now: now)
        guard delay > 0 else { shown = tab; return }
        pending = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            self?.shown = tab
        }
    }
}
