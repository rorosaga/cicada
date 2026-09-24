import SwiftUI

/// R-HO9 — the painting's own colours for what the app draws because paint cannot move (ART_DIRECTION §2's
/// motion-layer rows): seeds, fireflies, stars and the breathing light. They are the art's, not the UI's — the same in
/// both themes, never a `CicadaTheme` token (§2: "none of these colours enters CicadaTheme", DR-13), and only
/// `PaintedScene` names them.
enum ScenePaint {
    static let seed = Color(hex: 0xFFFDF6)
    static let seedAfternoon = Color(hex: 0xFBE3B8)
    static let fireflyCore = Color(hex: 0xF4D98B)
    static let fireflyGlow = Color(hex: 0xE9B75E)
    static let star = Color(hex: 0xE6EAF5)

    static func light(_ time: SceneTime) -> Color {
        switch time {
        case .day: Color(hex: 0xF6EBC8)        // §2 day "Sunlight"
        case .afternoon: Color(hex: 0xFBE7B5)  // §2 afternoon "Sun"
        case .night: Color(hex: 0xB8BEDC)      // §2 night "Moon halo"
        }
    }
}
