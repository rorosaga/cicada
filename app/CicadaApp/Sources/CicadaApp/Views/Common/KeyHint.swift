import SwiftUI

/// The one key hint (DR-49): at least 18 × 18 pt, `radiusXS`, `bgKey`, 11 medium SF — never
/// mono. It appears wherever a key acts, and every key it shows has a pointer equivalent beside
/// it. Decorative to VoiceOver: the control it sits in already names its shortcut.
struct KeyHint: View {
    let keys: String
    init(_ keys: String) { self.keys = keys }

    var body: some View {
        Text(keys)
            .font(CicadaTheme.font(size: 11, weight: .medium))
            .foregroundStyle(CicadaTheme.keyGlyph)
            .padding(.horizontal, CicadaTheme.scaled(5))
            .frame(minWidth: CicadaTheme.scaled(18), minHeight: CicadaTheme.scaled(18))
            .background(CicadaTheme.shape(CicadaTheme.radiusXS).fill(CicadaTheme.bgKey))
            .accessibilityHidden(true)
    }
}
