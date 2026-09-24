import SwiftUI

/// Where Home's band sits (F-09, R-HO6): its height. The crop, the fade and every layer are `SceneFraming.hero`'s.
enum HomeBandLayout {
    /// F-09's living band (R-HO6; was the D-Home mock's 120, R-HS2).
    static let bandHeight: CGFloat = 208
}

/// Home's band (DS-3b, F-09; DR-13): the living painting in its `.hero` framing — the person's Scene over the clock,
/// never the theme (G144), the meadow line at two thirds of the band, faded into `bgBase` below it. **Paint only:**
/// no word and no number sits on it (DR-13, DR-50); Home's headline is the next row down. A bundle that lost the
/// painting draws nothing, and the band is just the window.
struct HomeHeroBand: View {
    var body: some View { PaintedScene(.hero(band: HomeBandLayout.bandHeight)) }
}
