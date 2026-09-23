import SwiftUI

/// R-IB13 — "who reads what you save" on every onboarding surface goes through
/// this one view. Track O's `EngineChooser(style: .compact)` replaces the body
/// and nothing else changes. With `pick` (the Welcome) a click only rings the
/// card and Start writes it (§4.1.7 step 2, only if the person clicked); without
/// it (Getting started) a click commits, as Settings → Sleep does.
struct EngineChoice: View {
    var pick: Binding<String?>? = nil

    var body: some View {
        EngineCard(style: .compact, pick: pick)
    }
}
