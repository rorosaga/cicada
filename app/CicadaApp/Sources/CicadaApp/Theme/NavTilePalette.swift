import SwiftUI

/// The sidebar's icon tiles (owner 2026-11-24, DESIGN_RULES §9): one small rounded square per destination, a flat fill
/// of that destination's hue, the page's symbol on it in white. This file is the whole palette — nine named tokens, each
/// with a dark and a light value — and nothing else in the app reads a tile colour.
///
/// **It is not the accent and not a data hue.** The accent keeps its six uses (DR-5); the entity, context, status and
/// inbox-kind hues keep their values (DR-8). A tile hue encodes nothing: the label says which page it is, the colour
/// only helps the eye find the row, so it is never the only cue (`NavRailCell` draws it beside the name, and the rail's
/// tooltip and accessibility label carry the name). Selection is never a tile's job: the row's neutral fill says it.
///
/// **What each value had to clear** (`NavTilePaletteTests` holds every number):
/// - the white glyph ≥ 3:1 on its tile in both themes (DR-3's glyph bar; the lowest is 3.17:1, Clusters in dark), and
///   ≥ 4.5:1 when the person turned Increase Contrast on (`increasedContrast`, the same hue 25 % deeper);
/// - the tile itself ≥ 3:1 against the rail's own surface, so the shape reads in both themes;
/// - the nine hues told apart: CIE76 ΔE ≥ 16 for normal vision and ≥ 9 under a simulated protan, deutan or tritan
///   eye (Machado et al. 2009, severity 1.0). Ten hues cannot be told apart by hue alone, so lightness is spent too:
///   a pair that shares a hue family differs in lightness (Sleep's lavender against Agents' purple).
///
/// Dark values sit calmly on graphite — saturated, never neon; light values are the same hues one step deeper, so the
/// white glyph holds.
extension CicadaTheme {
    /// The ink on every tile: white in both themes, since the fill is an identity hue, not a theme surface (`onFill`).
    static var tileGlyph: Color { .white }

    static var tileHome: Color { tile(NavTilePalette.home) }
    static var tileGraph: Color { tile(NavTilePalette.graph) }
    static var tileClusters: Color { tile(NavTilePalette.clusters) }
    static var tileSkills: Color { tile(NavTilePalette.skills) }
    static var tileSleep: Color { tile(NavTilePalette.sleep) }
    static var tileSources: Color { tile(NavTilePalette.sources) }
    static var tileProjects: Color { tile(NavTilePalette.projects) }
    static var tileAgents: Color { tile(NavTilePalette.agents) }
    static var tileTraces: Color { tile(NavTilePalette.traces) }

    /// The tile fill for a page. The Inbox draws no cell of its own (it is Home's sub-view, ruling 48 (2)), so it wears
    /// Home's. `increasedContrast` is the system's Increase Contrast: the same hue, deeper.
    static func navTile(_ tab: AppTab, increasedContrast: Bool = false) -> Color {
        let pair = NavTilePalette.pair(for: tab)
        let hex = mode == .dark ? pair.dark : pair.light
        return Color(hex: increasedContrast ? NavTilePalette.deepened(hex) : hex)
    }

    private static func tile(_ pair: NavTilePalette.Pair) -> Color { Color(hex: mode == .dark ? pair.dark : pair.light) }
}

/// The values themselves, public to the tests so a number in DESIGN_RULES §3.9 and the code cannot drift apart.
enum NavTilePalette {
    struct Pair: Hashable { let dark: UInt32; let light: UInt32 }

    static let home = Pair(dark: 0x2F6FE4, light: 0x2563D6)       // blue
    static let graph = Pair(dark: 0x32894C, light: 0x2A7A41)      // green
    static let clusters = Pair(dark: 0xB38B1D, light: 0xA67B0E)   // amber
    static let skills = Pair(dark: 0xC9382A, light: 0xB22E1F)     // red
    static let sleep = Pair(dark: 0x8A80DE, light: 0x7468CC)      // lavender
    static let sources = Pair(dark: 0xD6407F, light: 0xBF356E)    // pink
    static let projects = Pair(dark: 0x13877F, light: 0x0E7871)   // teal
    static let agents = Pair(dark: 0x8744BC, light: 0x742FA6)     // purple
    static let traces = Pair(dark: 0x6E88A8, light: 0x5C7594)     // slate

    static func pair(for tab: AppTab) -> Pair {
        switch tab {
        case .home, .inbox: home
        case .graph: graph
        case .clusters: clusters
        case .skills: skills
        case .sleep: sleep
        case .sources: sources
        case .projects: projects
        case .agents: agents
        case .traces: traces
        }
    }

    /// The share of each channel Increase Contrast keeps: the hue is the same, 25 % darker.
    static let deepen: Double = 0.75

    static func deepened(_ hex: UInt32) -> UInt32 {
        func channel(_ shift: UInt32) -> UInt32 { UInt32((Double((hex >> shift) & 0xFF) * deepen).rounded()) << shift }
        return channel(16) | channel(8) | channel(0)
    }
}
