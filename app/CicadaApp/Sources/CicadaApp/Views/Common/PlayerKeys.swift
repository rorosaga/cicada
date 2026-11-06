import SwiftUI

/// ROR-131 — the keys every in-app player answers, and the pure rules behind them (no view, no AVFoundation, so each
/// is a plain XCTest against `FakePlaybackController`, the `VideoPlayerModel` grammar).
///
/// Space or K plays and pauses; ← → skip 5 seconds, J L skip 10; M mutes. They are scoped to the player's own container
/// (R10): a global shortcut would eat a text field's keys elsewhere in the window.
enum PlayerKeys {
    static let step = 5.0
    static let longStep = 10.0
    static let speeds: [Double] = [0.75, 1, 1.25, 1.5, 2]

    enum Action: Equatable {
        case toggle, skip(Double), mute
    }

    /// What a key means, nil for a key the player has no use for (so it is left to the rest of the window).
    static func action(for key: KeyEquivalent) -> Action? {
        switch key {
        case .space, "k": .toggle
        case .leftArrow: .skip(-step)
        case .rightArrow: .skip(step)
        case "j": .skip(-longStep)
        case "l": .skip(longStep)
        case "m": .mute
        default: nil
        }
    }

    /// Where a skip lands: never before the start, never past the end (when the length is known).
    static func skipped(from time: Double, by delta: Double, length: Double?) -> Double {
        let target = (time.isFinite ? time : 0) + delta
        let upper = length.map { max(0, $0) } ?? .infinity
        return min(max(0, target), upper)
    }

    /// Runs an action on the controller; false when there is nothing to act on.
    @discardableResult
    static func perform(_ action: Action, on controller: VideoPlaybackController?) -> Bool {
        guard let controller else { return false }
        switch action {
        case .toggle: controller.toggle()
        case .skip(let delta): controller.seek(to: skipped(from: controller.currentTime, by: delta, length: controller.length))
        case .mute: controller.isMuted.toggle()
        }
        return true
    }

    /// `1×`, `1.25×`, `0.75×` — the speed menu's label.
    static func speedLabel(_ speed: Double) -> String {
        let text = speed == speed.rounded() ? String(Int(speed)) : String(speed)
        return text + "×"
    }
}

extension View {
    /// Makes the container focusable and answers `PlayerKeys` for `controller`. A held arrow keeps skipping; a held
    /// space does not flip play and pause.
    func playerKeys(_ controller: VideoPlaybackController?) -> some View {
        focusable()
            .onKeyPress(keys: [.space, .leftArrow, .rightArrow, "j", "k", "l", "m"], phases: [.down, .repeat]) { press in
                guard let action = PlayerKeys.action(for: press.key) else { return .ignored }
                if press.phase == .repeat, action == .toggle || action == .mute { return .handled }
                return PlayerKeys.perform(action, on: controller) ? .handled : .ignored
            }
    }
}
