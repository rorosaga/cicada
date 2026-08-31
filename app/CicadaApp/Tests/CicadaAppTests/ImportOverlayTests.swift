import XCTest
@testable import CicadaApp

/// G71 §4.2–4.3 — the export overlay: a written step path per platform, and a
/// drop → live preview → confirm → summary machine over the staging-free
/// preview endpoint.
final class ImportOverlayTests: XCTestCase {

    // MARK: - Wire decoding

    func testPreviewDecodesTheBackendEnvelope() throws {
        let json = """
        {"recognized": true, "platform": "instagram", "total": 214,
         "collections": [{"name": "Recipes", "kind": "collection", "count": 182},
                         {"name": "Type inspo", "kind": "collection", "count": 32}],
         "warnings": []}
        """.data(using: .utf8)!
        let preview = try JSONDecoder().decode(UploadPreview.self, from: json)
        XCTAssertTrue(preview.recognized)
        XCTAssertEqual(preview.platform, "instagram")
        XCTAssertEqual(preview.total, 214)
        XCTAssertEqual(preview.collections.count, 2)
        XCTAssertEqual(preview.collections[0].name, "Recipes")
        XCTAssertEqual(preview.collections[0].count, 182)
    }

    func testPreviewToleratesAMissingFieldFromAnOlderBackend() throws {
        let json = #"{"recognized": false}"#.data(using: .utf8)!
        let preview = try JSONDecoder().decode(UploadPreview.self, from: json)
        XCTAssertFalse(preview.recognized)
        XCTAssertEqual(preview.platform, "unknown")
        XCTAssertEqual(preview.total, 0)
        XCTAssertTrue(preview.collections.isEmpty)
        XCTAssertTrue(preview.warnings.isEmpty)
    }

    func testCollectionIdsAreUniqueSoTheListDoesNotCollapseRows() {
        let a = UploadCollection(name: "Recipes", kind: "collection", count: 1)
        let b = UploadCollection(name: "Recipes", kind: "board", count: 1)
        XCTAssertNotEqual(a.id, b.id)
    }

    // MARK: - Copy

    func testTheTotalLineNamesBothNumbers() {
        let preview = UploadPreview(
            recognized: true, platform: "instagram", total: 214,
            collections: [UploadCollection(name: "Recipes", kind: "collection", count: 182),
                          UploadCollection(name: "Type inspo", kind: "collection", count: 32)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "214 items across 2 collections")
    }

    func testTheTotalLineIsSingularForOneCollection() {
        let preview = UploadPreview(
            recognized: true, platform: "linkedin", total: 1,
            collections: [UploadCollection(name: "Saved Items", kind: "saved", count: 1)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "1 item in 1 saved")
    }

    func testTheTotalLinePluralisesAwkwardKindsWithoutInventingWords() {
        let preview = UploadPreview(
            recognized: true, platform: "reddit", total: 5,
            collections: [UploadCollection(name: "Saved posts", kind: "saved", count: 3),
                          UploadCollection(name: "Saved comments", kind: "saved", count: 2)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "5 items across 2 saved sets")
    }

    func testTheSummaryShowsNewAndAlreadySaved() {
        let response = UploadResponse(status: "ok", episodesCreated: 182, episodesUpdated: 0,
                                      duplicatesSkipped: 32, message: "", source: "Instagram Saved")
        XCTAssertEqual(ImportOverlayState.summary(response), "182 new · 32 already saved")
    }

    func testTheSummarySaysSoWhenNothingIsNew() {
        let response = UploadResponse(status: "ok", episodesCreated: 0, episodesUpdated: 0,
                                      duplicatesSkipped: 32, message: "", source: "Instagram Saved")
        XCTAssertEqual(ImportOverlayState.summary(response), "Nothing new · 32 already saved")
    }

    // MARK: - Stage machine

    func testAnUnrecognizedFileFailsWithItsWarningRatherThanOfferingConfirm() {
        let preview = UploadPreview(recognized: false, platform: "unknown", total: 0,
                                    collections: [], warnings: ["Unsupported file format."])
        let url = URL(fileURLWithPath: "/tmp/photo.heic")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url),
                       .failed("Unsupported file format."))
    }

    func testAnUnrecognizedFileWithNoWarningStillFailsHonestly() {
        let preview = UploadPreview(recognized: false, platform: "unknown", total: 0,
                                    collections: [], warnings: [])
        let url = URL(fileURLWithPath: "/tmp/x.bin")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url),
                       .failed("Cicada could not read this file as a saved-content export."))
    }

    func testARecognizedFileMovesToPreviewCarryingTheFile() {
        let preview = UploadPreview(
            recognized: true, platform: "instagram", total: 3,
            collections: [UploadCollection(name: "Recipes", kind: "collection", count: 3)],
            warnings: [])
        let url = URL(fileURLWithPath: "/tmp/saved_posts.json")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url), .preview(preview, url))
    }

    // MARK: - Step paths

    func testEveryExportVendorHasABreadcrumbStepPath() {
        for vendor in WalkthroughVendor.allCases {
            let path = vendor.stepPath
            XCTAssertFalse(path.isEmpty, "\(vendor.rawValue) has no step path")
            XCTAssertTrue(path.contains(">"),
                          "\(vendor.rawValue) step path is not a breadcrumb: \(path)")
        }
    }

    func testTheInstagramStepPathIsTheOneFromTheSpec() {
        XCTAssertEqual(
            WalkthroughVendor.instagram.stepPath,
            "Settings > Accounts Center > Your information and permissions > "
            + "Download your information > Download or transfer > "
            + "Some of your information > Saved > JSON")
    }

    /// The other export platforms — TikTok, LinkedIn, Reddit's GDPR export —
    /// get the same written-equivalent treatment as Instagram, not a shrug.
    func testEveryExportPlatformHasItsOwnDistinctStepPath() {
        let paths = Set(WalkthroughVendor.allCases.map(\.stepPath))
        XCTAssertEqual(paths.count, WalkthroughVendor.allCases.count,
                       "two vendors share a step path")
    }
}
