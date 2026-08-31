import XCTest
@testable import CicadaApp

/// The import walkthroughs (G64): every vendor must carry a real, reachable
/// settings URL and a short numbered step list. These strings are the whole
/// feature — a typo'd host silently opens nothing, so pin them.
final class WalkthroughTests: XCTestCase {

    func testEveryVendorHasAnHTTPSExportURL() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertEqual(vendor.exportURL.scheme, "https", "\(vendor.rawValue)")
            XCTAssertNotNil(vendor.exportURL.host, "\(vendor.rawValue)")
        }
    }

    func testTheVendorURLTableIsExactlyTheSpecTable() {
        let table = Dictionary(uniqueKeysWithValues:
            WalkthroughVendor.allCases.map { ($0.rawValue, $0.exportURL.absoluteString) })
        XCTAssertEqual(table, [
            "claude": "https://claude.ai/settings/data-privacy-controls",
            "chatgpt": "https://chatgpt.com/#settings/DataControls",
            "takeout": "https://takeout.google.com/",
            "instagram": "https://accountscenter.instagram.com/info_and_permissions/dyi/",
            "tiktok": "https://www.tiktok.com/setting/download-your-data",
            "linkedin": "https://www.linkedin.com/mypreferences/d/download-my-data",
            "redditExport": "https://www.reddit.com/settings/data-request",
        ])
    }

    func testEveryVendorHasThreeOrFourSteps() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertTrue((3...4).contains(vendor.steps.count),
                          "\(vendor.rawValue) has \(vendor.steps.count) steps")
            XCTAssertFalse(vendor.steps.contains(where: \.isEmpty), "\(vendor.rawValue)")
        }
    }

    func testVideoNamesAreDistinctAndFilenameSafe() {
        let names = WalkthroughVendor.allCases.map(\.videoName)
        XCTAssertEqual(Set(names).count, names.count)
        XCTAssertTrue(names.allSatisfy { $0.allSatisfy { c in c.isLetter || c.isNumber || c == "-" } })
    }
}
