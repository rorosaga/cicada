import SwiftUI

/// Settings → From anywhere (G135's page, promoted to its own row by G139 A1).
/// Track R's `RemoteAccessView` renders unchanged beneath a Settings header —
/// its switch, reach card, connectors and shown-once sheets are its own
/// (R-O12). Search lands on this header: the page's rows live inside Track R's
/// view, and adding anchors there would change it. The header sits outside
/// Track R's scroll view, so it is always on screen and a landing needs no
/// scroll.
struct FromAnywhereView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SettingsDetailHeader(section: .remote)
                .padding(.horizontal, CicadaTheme.spacingXL)
            RemoteAccessView()
        }
    }
}
