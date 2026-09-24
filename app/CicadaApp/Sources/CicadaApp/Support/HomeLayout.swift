import CoreGraphics
import Foundation

/// Track I T6 (design §6.2) — Home's "every number appears once" rule, pure,
/// for part b: while Getting started shows its "Read what came in" row (until
/// the first read), TODAY omits its own waiting clause. DS-3b adds the D-Home
/// mock's column geometry (R-HS2, R-HS6), so the page's numbers are table-tested rather than eyeballed (`HomeLayoutTests`).
enum HomeLayout {
    /// D-Home (R-HS2, R-HS6): one 760 pt column (DR-36), the field 640 pt inside it (the approved
    /// mock; §10's 560 lost to it), the headline 8 / 20 pt off its neighbours, 24 pt between blocks,
    /// 6 pt from a label to its block, and 64 pt under the last one.
    static let columnWidth: CGFloat = 760
    static let fieldWidth: CGFloat = 640
    static let headlineTop: CGFloat = 8
    static let headlineBottom: CGFloat = 20
    static let blockGap: CGFloat = 24
    static let labelGap: CGFloat = 6
    static let bottomPadding: CGFloat = 64
    static let gutter: CGFloat = 40
    static let blockInset: CGFloat = 4

    static func showsWaitingInToday(gettingStartedVisible: Bool, hasRunBefore: Bool) -> Bool {
        !(gettingStartedVisible && !hasRunBefore)
    }
}
