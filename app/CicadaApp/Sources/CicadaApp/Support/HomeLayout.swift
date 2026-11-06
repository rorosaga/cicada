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
    /// ROR-118 — the headline and the field are the page's lead: the headline is 34 pt. Round 2: it starts a fifth of
    /// the viewport down (24 pt at the least, 150 pt at the most), so the lead sits at the optical centre of the window
    /// and the page is not all weight at the top over an empty lower half.
    static let headlineSize: CGFloat = 34
    static func headlineTop(viewportHeight: CGFloat) -> CGFloat {
        min(140, max(headlineTop, (viewportHeight * 0.17).rounded()))
    }
    /// Round 3 — the worm over the headline. With it the lead is taller, so it starts 17 % of the viewport down (24 pt at
    /// the least, 140 pt at the most) and the block sits at the window's optical centre.
    /// Round 4 — drawn at 3 points to the art pixel (it was 2: 112 pt wide, soft beside the thin icons), an integer so
    /// every pixel stays square and crisp, and cropped to the pixels the sprite ever draws (`greeterInk`, art pixels:
    /// x 4–60, y 3–48 across every mood), so its transparent margin does not push the headline down.
    static let greeterCell: CGFloat = 3
    static let greeterInk = CGRect(x: 4, y: 3, width: 56, height: 45)
    static let greeterGap: CGFloat = 12
    static let headlineBottom: CGFloat = 26
    static let blockGap: CGFloat = 24
    /// The field is a block like the rest (owner 2026-10-06): the first card sits one block gap under it.
    static let fieldToFirstBlock: CGFloat = blockGap
    static let labelGap: CGFloat = 6
    /// ROR-118 — the gap between the quiet rows of Today and Last read (no card, no label), and the lead question's
    /// card inset.
    static let pulseGap: CGFloat = 2
    static let leadInset: CGFloat = 18
    /// ROR-118 round 2 — a quiet row's glyph column (no tile) and its gap to the words, so every row's text starts on one
    /// edge, under the lead card's own text.
    static let rowGlyph: CGFloat = 20
    static let leadPicture: CGFloat = 44
    /// ROR-118 round 3 — a page chip's picture under Last read (the smallest `EntityPicture` draws is 20).
    static let chipPicture: CGFloat = 22
    static let bottomPadding: CGFloat = 64
    static let gutter: CGFloat = 40
    static let blockInset: CGFloat = 4

    static func showsWaitingInToday(gettingStartedVisible: Bool, hasRunBefore: Bool) -> Bool {
        !(gettingStartedVisible && !hasRunBefore)
    }
}
