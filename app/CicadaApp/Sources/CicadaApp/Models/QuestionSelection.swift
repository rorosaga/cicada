import Foundation

/// Pure keyboard-navigation model for `QuestionView` (G60 §2.6, extended by
/// G115 Phase 1 with `1–4`, `Esc` and the recommended-first highlight).
///
/// Rows are the options, followed by the "Other…" row when `allowOther`.
/// Kept out of the `View` so the ↑/↓/⏎/`o`/`Esc`/digit behaviour is
/// unit-testable — every piece of new inbox logic that CAN be pure lives here
/// rather than in a body.
struct QuestionSelection: Equatable {
    let optionCount: Int
    let allowOther: Bool

    private(set) var index: Int = 0
    /// True once the user has opened the free-text row (via ⏎ on it, or `o`).
    private(set) var otherExpanded: Bool = false

    enum Action: Equatable {
        case pick(Int)
        case openOther
        /// `Esc` with the free-text row open: close the row, keep the card.
        case closeOther
        /// `Esc` otherwise: collapse the card. NO write — a skip leaves no
        /// trace (G115 §7); the backend's `action: skip` is a ledger row and
        /// is deliberately not this.
        case collapse
    }

    /// `initialIndex` is the `(Recommended)` row (G115 §7: recommended first,
    /// ⏎ accepts it); out of range → the first row, never a missing one.
    init(optionCount: Int, allowOther: Bool, initialIndex: Int? = nil) {
        self.optionCount = max(0, optionCount)
        self.allowOther = allowOther
        if let i = initialIndex, i >= 0, i < self.optionCount { index = i }
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

    /// `1`–`9` picks that option (1-based); the Other row is never numbered.
    mutating func pickNumber(_ n: Int) -> Action? {
        guard n >= 1, n <= optionCount else { return nil }
        index = n - 1
        return .pick(index)
    }

    /// `Esc`: close the free-text row if it is open, else collapse the card.
    mutating func escape() -> Action {
        if otherExpanded {
            otherExpanded = false
            index = min(index, max(0, optionCount - 1))
            return .closeOther
        }
        return .collapse
    }
}
