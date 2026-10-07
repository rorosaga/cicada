import SwiftUI

/// The shell's numbers and its pure decisions (DESIGN_RULES §5.1, §5.5). Views render these;
/// NavRailTests reads them. Every dimension is at uiScale 1 and scales through
/// `CicadaTheme.scaled` (DR-70).
enum ShellMetrics {
    /// R-DS15 — rail or labelled sidebar, per viewer. A convenience, so `UserDefaults`.
    static let labelledKey = "cicada.shell.labelledSidebar"
    static let railWidth: CGFloat = 56
    static let sidebarWidth: CGFloat = 208
    static let railCell: CGFloat = 36          // at a 40 pt pitch (a 4 pt gap)
    static let sidebarRow: CGFloat = 32
    static let railInset: CGFloat = 10         // (56 − 36) / 2
    static let commandBarWidth: CGFloat = 520
    static let commandBarHeight: CGFloat = 32

    static func navWidth(labelled: Bool) -> CGFloat {
        CicadaTheme.scaled(labelled ? sidebarWidth : railWidth)
    }
}

/// One rail cell's words and key — the rail's order is `AppTab.allCases`, which is its ⌘ order.
enum RailItem {
    static func digit(for tab: AppTab) -> Int { (AppTab.allCases.firstIndex(of: tab) ?? 0) + 1 }
    static func key(for tab: AppTab) -> KeyEquivalent { KeyEquivalent(Character(String(digit(for: tab)))) }
    static func shortcut(for tab: AppTab) -> String { "⌘\(digit(for: tab))" }
    static func tooltipTitle(_ tab: AppTab, busy: Bool) -> String {
        busy ? "\(tab.title) · \(Copy.railConsolidating)" : tab.title
    }
    static func accessibilityLabel(_ tab: AppTab, count: Int, busy: Bool) -> String {
        var label = tab.title
        if count > 0 { label += ", \(UsageFormat.count(count)) pending" }
        if busy { label += ", \(Copy.railConsolidating)" }
        return label
    }
}

/// R-DS14 — when a rail tooltip may open.
enum RailTooltipTiming {
    static func delay(lastHiddenAt: Date?, isShowing: Bool, now: Date) -> TimeInterval {
        if isShowing { return 0 }
        if let last = lastHiddenAt, now.timeIntervalSince(last) <= CicadaMotion.railTooltipWarmWindow { return 0 }
        return CicadaMotion.railTooltipDelay
    }
}

/// R-DS20 — the titlebar's items under a modal. The toolbar itself never goes away, so the
/// titlebar never changes height under the person's pointer.
struct ShellChrome: Equatable {
    var welcomeShowing = false
    var settingsOpen = false
    /// G152 — the tour is modal like the Settings panel, but the titlebar stays lit: its first stop points at the
    /// command bar. Inert, not dimmed (ruling R-DT10).
    var tourActive = false

    var itemsHidden: Bool { welcomeShowing }
    var itemsDisabled: Bool { welcomeShowing || settingsOpen || tourActive }
    var itemOpacity: Double { welcomeShowing ? 0 : (settingsOpen ? 0.4 : 1) }
}

extension View {
    func shellChrome(_ chrome: ShellChrome) -> some View {
        opacity(chrome.itemOpacity)
            .disabled(chrome.itemsDisabled)
            .accessibilityHidden(chrome.itemsHidden)
    }
}

/// How the rail, the titlebar band and the page meet at the page's top-leading corner (owner 2026-10-07). One
/// compile-time switch, never a setting: the 2026-10-06 fillet painted `bgRail` into the page's corner under a `bgBase`
/// band, so the rail ended in a horn along the titlebar line. Both answers are complete; the owner picks one.
enum RailCorner: CaseIterable {
    /// A — one frame: the titlebar band takes the rail's surface, so band and rail read as one L-shaped chrome, and the
    /// page is a panel whose top-leading corner is rounded and clips what it holds.
    case oneFrame
    /// B — rounded rail: the band stays the window's `bgBase`; the rail column's own top-trailing corner is rounded and
    /// the page stays square under it — no colour reaches into the page.
    case roundedRail

    /// The switch. A until the owner picks (DESIGN_RULES, 2026-10-07 ruling).
    static let current: RailCorner = .oneFrame

    /// Whether the titlebar band is painted with the rail's surface (`CicadaTheme.titlebarBackground`).
    var titlebarIsRail: Bool { self == .oneFrame }

    /// The rail column's fill. Square in A (it and the band are one L); rounded at its top-trailing corner in B.
    var railShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(topTrailingRadius: self == .roundedRail ? CicadaTheme.contentCornerRadius : 0,
                               style: .continuous)
    }

    /// The page panel's clip and fill in A; `nil` in B, where the page is neither clipped nor painted by the shell.
    var contentShape: UnevenRoundedRectangle? {
        self == .oneFrame
            ? UnevenRoundedRectangle(topLeadingRadius: CicadaTheme.contentCornerRadius, style: .continuous) : nil
    }
}

/// A's page panel: the page's own `bgBase` in the panel shape, clipped to it, so the rounded corner shows the band's and
/// the rail's surface and nothing a page scrolls up draws over the band. B leaves the page exactly as it was.
struct ShellContentPanel: ViewModifier {
    var corner: RailCorner = .current

    func body(content: Content) -> some View {
        if let shape = corner.contentShape {
            content
                .background(alignment: .top) { shape.fill(CicadaTheme.background) }
                .clipShape(shape)
        } else {
            content
        }
    }
}

extension View {
    /// The one door for the page host's corner treatment (`RailCorner`).
    func shellContentPanel(_ corner: RailCorner = .current) -> some View { modifier(ShellContentPanel(corner: corner)) }
}
