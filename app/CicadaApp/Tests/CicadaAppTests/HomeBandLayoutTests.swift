import XCTest
@testable import CicadaApp

/// R-IB10 — text never on paint: the drifting cloud stays in the outer quarter
/// and never crosses the headline, at any width or zoom.
final class HomeBandLayoutTests: XCTestCase {
    func testTheCloudNeverCrossesTheHeadlineAtAnyWidthOrZoom() {
        for width in stride(from: CGFloat(480), through: 1800, by: 40) {
            for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
                let head = HomeBandLayout.headlineFrame(width: width, scale: scale)
                XCTAssertLessThanOrEqual(head.maxY, HomeBandLayout.bandHeight * scale, "width \(width) scale \(scale)")
                guard let cloud = HomeBandLayout.cloudFrame(width: width, scale: scale) else { continue }
                let drifted = cloud.insetBy(dx: -CicadaMotion.ambientMaxAmplitude, dy: 0)
                XCTAssertFalse(drifted.intersects(head), "width \(width) scale \(scale)")
                XCTAssertGreaterThanOrEqual(cloud.minX, width * 0.75, "the cloud stays in the outer quarter")
            }
        }
    }

    func testANarrowBandDropsTheCloudRatherThanSqueezeTheHeadline() {
        XCTAssertNil(HomeBandLayout.cloudFrame(width: 560, scale: 1))
        XCTAssertNotNil(HomeBandLayout.cloudFrame(width: 900, scale: 1))
    }
}
