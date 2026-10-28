import Foundation
import Observation

/// Track I part b (R-IB4, R-IB5) — Home's field: its own `FindPaletteModel`
/// (so a ⌘K elsewhere never wipes what was left typed here), sharing the app's
/// one Ask, keeping no recents. `focusRequest` is a nonce `FindPanelBody`
/// watches — ⌘K on Home and ⌘1 both focus the field through it.
@MainActor
@Observable
final class HomeSearch {
    let model: FindPaletteModel
    private(set) var focusRequest = 0
    /// Ruling 48 (8) — the catch-up chat open on Home. Held here, with the field, so opening a page from the chat and
    /// coming back finds the conversation where it was; Home's rail cell clicked again or a bank switch ends it.
    var catchup: CatchupSession?

    init(model: FindPaletteModel) { self.model = model }

    func focus(prefill: String = "", mode: FindMode = .find) {
        if !prefill.isEmpty {
            model.setMode(.find)
            model.setQuery(prefill)
        }
        if mode == .ask { model.setMode(.ask) }
        focusRequest &+= 1
    }
}
