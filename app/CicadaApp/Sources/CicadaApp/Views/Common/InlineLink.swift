import SwiftUI

/// DR-5 use 5 — a link: 12 medium in `accentText`, no fill, the label's own words (a "›" when it
/// goes to another page). One definition for Home's "Sleep ›" / "All 6 ›" and the Sleep menu's
/// "More in Settings → Engines ›", so a link is never an ad-hoc `Button` tinted by hand.
/// `accentText` (not the accent) is what clears 4.5:1 in light mode (DR-6).
struct InlineLink: View {
    let title: String
    var help: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(CicadaTheme.metaMediumFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.accentText)
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
    }
}
