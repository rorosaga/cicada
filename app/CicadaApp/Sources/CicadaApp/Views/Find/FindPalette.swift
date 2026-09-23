import SwiftUI

/// The ⌘K palette's chrome (round-3 design §3.1): an overlay on
/// `ContentView`'s root — not a sheet, which is modal to the title bar and
/// cannot be glass (A11) — 640 pt wide, its top at 14 % of the window,
/// Liquid Glass (`.control` = `Glass.regular`) around an opaque body (R-SU17),
/// over a light click-outside scrim.
struct FindPalette: View {
    let model: FindPaletteModel
    let open: (FindDestination) -> Void
    let close: () -> Void

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                Color.black.opacity(0.12)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture(perform: close)
                    .accessibilityHidden(true)
                FindPanelBody(model: model, placement: .palette, open: open, close: close)
                    .frame(width: min(CicadaTheme.scaled(640), geo.size.width - CicadaTheme.spacingXL * 2),
                           height: min(CicadaTheme.scaled(560), geo.size.height * 0.72))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
                    .liquidGlass(.control, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
                    .shadow(color: .black.opacity(0.25), radius: 24, y: 10)
                    .padding(.top, geo.size.height * 0.14)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Find in memory")
                    .accessibilityAddTraits(.isModal)
            }
            .frame(maxWidth: .infinity)
        }
    }
}
