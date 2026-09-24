import SwiftUI

enum FindKeyAction: Equatable {
    case move(FindStep)
    case secondary
    case askNow
    case escape
    case none
}

/// The palette's keys (design §3.4; R-SU11) as one pure map, so every
/// binding is tested. Plain ⏎ is `.none` on purpose: it stays on the field's
/// `onSubmit`, the path the Graph's find overlay uses; everything else arrives
/// through ONE `.onKeyPress` handler.
enum FindKeymap {
    /// What a Shift-Tab keypress can report as its key (backtab).
    static let backtab = KeyEquivalent("\u{19}")

    static func action(key: KeyEquivalent, modifiers: EventModifiers, mode: FindMode) -> FindKeyAction {
        if key == .escape { return .escape }
        guard mode == .find else { return .none }   // Ask shows an answer, not a list
        switch key {
        case .downArrow: return modifiers.contains(.command) ? .move(.last) : .move(.next)
        case .upArrow: return modifiers.contains(.command) ? .move(.first) : .move(.previous)
        case .tab: return modifiers.contains(.shift) ? .move(.previousGroup) : .move(.nextGroup)
        case backtab: return .move(.previousGroup)
        case .return:
            if modifiers.contains(.command) { return .askNow }
            if modifiers.contains(.option) { return .secondary }
            return .none
        default: return .none
        }
    }
}
