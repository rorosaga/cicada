import XCTest
@testable import CicadaApp

/// Owner 2026-11-25 — leaving the ask-why panel, as the tests say it: a click somewhere else no longer closes the
/// panel at once, so "the person left" is that click and then the whole wait (`SaveWhyPolicy.awayCooldown`), or the
/// untouched question's bar filling.
extension SaveWhyCenter {
    @MainActor
    func leave() {
        send(.clickOutside)
        send(.timeout)
    }
}

extension SaveWhyPanelState {
    mutating func leave() -> [Effect] {
        _ = send(.clickOutside)
        return send(.timeout)
    }
}
