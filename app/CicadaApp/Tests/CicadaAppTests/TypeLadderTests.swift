import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-16 — the ladder, and DR-53's icon sizes, as the rules spell them.
final class TypeLadderTests: XCTestCase {
    override func tearDown() { CicadaTheme.uiScale = 1.0; super.tearDown() }

    func testTheLadderIsTheRulesSizesAndWeights() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(CicadaTheme.headingFont, CicadaTheme.font(size: 17, weight: .semibold))
        XCTAssertEqual(CicadaTheme.detailBodyFont, CicadaTheme.font(size: 14))
        XCTAssertEqual(CicadaTheme.bodyFont, CicadaTheme.font(size: 13), "R-DS9: body stays 13 off detail surfaces")
        XCTAssertEqual(CicadaTheme.rowFont, CicadaTheme.font(size: 13, weight: .medium))
        XCTAssertEqual(CicadaTheme.metaFont, CicadaTheme.font(size: 12))
        XCTAssertEqual(CicadaTheme.metaMediumFont, CicadaTheme.font(size: 12, weight: .medium))
        XCTAssertEqual(CicadaTheme.labelFont, CicadaTheme.font(size: 11, weight: .medium), "DR-20: no mono, no caps")
        XCTAssertEqual(CicadaTheme.badgeFont, CicadaTheme.font(size: 10, weight: .semibold))
        XCTAssertEqual(CicadaTheme.quoteLineSpacing, 7, "DR-16: SF 15's natural 18 pt line + 7 = 25")
    }

    func testIconSizesByRoleScale() {
        CicadaTheme.uiScale = 1.0
        let expected: [(CicadaTheme.IconRole, CGFloat)] = [(.rail, 18), (.railFoot, 17), (.titlebar, 16), (.sidebar, 16),
                                                           (.list, 14), (.commandBar, 13), (.inline, 12), (.badge, 10)]
        for (role, points) in expected { XCTAssertEqual(CicadaTheme.iconPoints(role), points, "\(role)") }
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(CicadaTheme.iconPoints(.rail), 25.2, accuracy: 0.05)
    }
}
