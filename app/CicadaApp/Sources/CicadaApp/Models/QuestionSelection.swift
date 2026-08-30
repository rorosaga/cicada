import Foundation

/// Pure keyboard-navigation model for `QuestionView` (G60 §2.6).
///
/// Rows are the options, followed by the "Other…" row when `allowOther`.
/// Kept out of the `View` so the ↑/↓/⏎/`o` behaviour is unit-testable — every
/// piece of new inbox logic that CAN be pure lives here rather than in a body.
struct QuestionSelection: Equatable {
    let optionCount: Int
    let allowOther: Bool

    private(set) var index: Int = 0
    /// True once the user has opened the free-text row (via ⏎ on it, or `o`).
    private(set) var otherExpanded: Bool = false

    enum Action: Equatable {
        case pick(Int)
        case openOther
    }

    init(optionCount: Int, allowOther: Bool) {
        self.optionCount = max(0, optionCount)
        self.allowOther = allowOther
    }

    /// Options + the optional Other… row.
    var rowCount: Int { optionCount + (allowOther ? 1 : 0) }

    var isOtherRow: Bool { allowOther && index == optionCount }

    mutating func moveDown() {
        guard rowCount > 0 else { return }
        index = (index + 1) % rowCount
    }

    mutating func moveUp() {
        guard rowCount > 0 else { return }
        index = (index - 1 + rowCount) % rowCount
    }

    /// Jump straight to the free-text row (the `o` shortcut).
    mutating func openOther() {
        guard allowOther else { return }
        index = optionCount
        otherExpanded = true
    }

    /// ⏎ on the highlighted row. `nil` when there is nothing to activate.
    mutating func activate() -> Action? {
        guard rowCount > 0 else { return nil }
        if isOtherRow {
            otherExpanded = true
            return .openOther
        }
        return .pick(index)
    }
}
