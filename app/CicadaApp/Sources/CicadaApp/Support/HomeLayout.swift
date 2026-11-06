import CoreGraphics
import Foundation

/// Track I T6 (design §6.2) — Home's "every number appears once" rule, pure,
/// for part b: while Getting started shows its "Read what came in" row (until
/// the first read), TODAY omits its own waiting clause. DS-3b adds the D-Home
/// mock's column geometry (R-HS2, R-HS6), so the page's numbers are table-tested rather than eyeballed (`HomeLayoutTests`).
enum HomeLayout {
    /// D-Home (R-HS2, R-HS6): one 760 pt column (DR-36), the field 640 pt inside it (the approved
    /// mock; §10's 560 lost to it), the headline 24 / 20 pt off its neighbours, 24 pt between blocks,
    /// 6 pt from a label to its block, and 64 pt under the last one.
    static let columnWidth: CGFloat = 760
    static let fieldWidth: CGFloat = 640
    /// The headline is Home's first content (the painted band retired, owner 2026-10-16; off since G189(a)): it takes
    /// the room pages' title inset (24 pt, `PageHeader`'s top), well inside DR-26's 120 pt.
    static let headlineTop: CGFloat = 24
    /// ROR-118 (round 1) — the headline and the field are the page's lead: the headline is 34 pt and starts a tenth of
    /// the viewport down (24 pt at the least, 88 pt at the most), so the lead sits where the eye lands and the rest
    /// reads as what follows it.
    static let headlineSize: CGFloat = 34
    static func headlineTop(viewportHeight: CGFloat) -> CGFloat {
        min(88, max(headlineTop, (viewportHeight * 0.1).rounded()))
    }
    static let headlineBottom: CGFloat = 22
    static let blockGap: CGFloat = 24
    /// The field is a block like the rest (owner 2026-10-06): the first card sits one block gap under it.
    static let fieldToFirstBlock: CGFloat = blockGap
    static let labelGap: CGFloat = 6
    /// ROR-118 — the gap between the quiet rows of Today and Last read (no card, no label), and the lead question's
    /// card inset.
    static let pulseGap: CGFloat = 2
    static let leadInset: CGFloat = 18
    static let leadPicture: CGFloat = 44
    static let bottomPadding: CGFloat = 64
    static let gutter: CGFloat = 40
    static let blockInset: CGFloat = 4

    static func showsWaitingInToday(gettingStartedVisible: Bool, hasRunBefore: Bool) -> Bool {
        !(gettingStartedVisible && !hasRunBefore)
    }
}
