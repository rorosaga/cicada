import XCTest
@testable import CicadaApp

/// C11 / R-PE4, R-PE15 — what the picture menu offers for each source, in words.
final class PictureMenuTests: XCTestCase {
    func testTheMenuOffersWhatTheSourceAllows() {
        XCTAssertEqual(PictureMenuModel.options(current: nil, detected: nil), [.add])
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: "/u", source: .upload), detected: nil),
                       [.change, .remove])
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: "/c", source: .contacts),
                                                detected: EntityPictureRef(url: "/c", source: .contacts)),
                       [.change, .useInitials])
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: nil, source: .initials),
                                                detected: EntityPictureRef(url: "/l", source: .logo)),
                       [.change, .useDetected(.logo)])
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: nil, source: .initials), detected: nil),
                       [.change], "nothing detected: nothing to go back to")
        // G159 (2026-10-09): a wrong public-profile photo is one click to replace and one to remove for good.
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: "/entities/b/photo", source: .profile),
                                                detected: EntityPictureRef(url: "/entities/b/photo", source: .profile)),
                       [.change, .useInitials])
        XCTAssertEqual(PictureMenuModel.options(current: EntityPictureRef(url: nil, source: .initials),
                                                detected: EntityPictureRef(url: "/entities/b/photo", source: .profile)),
                       [.change, .useDetected(.profile)])
    }

    func testEveryOptionHasPlainWords() {
        let options: [PictureMenuModel.Option] = [.change, .add, .useInitials, .remove, .useDetected(.contacts),
                                                  .useDetected(.logo), .useDetected(.thumbnail),
                                                  .useDetected(.profile)]
        for option in options {
            let words = Copy.People.optionLabel(option)
            XCTAssertFalse(words.isEmpty)
            XCTAssertFalse(words.contains("%") || words.contains("_"), words)
        }
        XCTAssertTrue(PictureActions.canEdit(.person) && PictureActions.canEdit(.media))
        XCTAssertFalse(PictureActions.canEdit(.hub), "a hub has no page to hold a picture")
        XCTAssertFalse(PictureActions.canEdit(.unknown))
    }
}
