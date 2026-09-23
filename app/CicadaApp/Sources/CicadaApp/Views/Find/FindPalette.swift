import SwiftUI

/// The ⌘K palette's chrome (G136; DR-23, R-DS17): an overlay on `ContentView`'s root — 640 pt,
/// `cornerRadius`, an opaque `bgMenu` floating surface (no glass: DR-14 does not list it), its top
/// 4 pt under the titlebar so it reads as dropping from the command bar, over the panel scrim.
/// It appears and leaves in one frame (DR-60).
struct FindPalette: View {
    let model: FindPaletteModel
    let open: (FindDestination) -> Void
    let close: () -> Void

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                CicadaTheme.scrimPanel
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture(perform: close)
                    .accessibilityHidden(true)
                FindPanelBody(model: model, placement: .palette, open: open, close: close)
                    .frame(width: FindPaletteLayout.width(container: geo.size.width),
                           height: FindPaletteLayout.height(container: geo.size.height))
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
                    .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                    .padding(.top, FindPaletteLayout.top)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Find in memory")
                    .accessibilityAddTraits(.isModal)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

/// R-DS17 — the palette's geometry, pure.
enum FindPaletteLayout {
    static let width: CGFloat = 640
    static let maxHeight: CGFloat = 560
    static func width(container: CGFloat) -> CGFloat {
        max(0, min(CicadaTheme.scaled(width), container - CicadaTheme.spacingXL * 2))
    }
    static func height(container: CGFloat) -> CGFloat {
        max(0, min(CicadaTheme.scaled(maxHeight), container * 0.72))
    }
    /// The command bar lives in AppKit's titlebar; the palette starts just under it.
    static var top: CGFloat { CicadaTheme.spacingXS }
}
