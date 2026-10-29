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

    /// Owner 2026-10-29: the picture is the control. A click with only a file to choose opens the picker at once;
    /// with anything else to offer it drops down the same choices as the right-click menu.
    func testAClickOnThePictureOffersItsChoices() {
        XCTAssertEqual(PictureChoices.plan([.add]), .pick)
        XCTAssertEqual(PictureChoices.plan([.change]), .pick, "initials chosen, nothing detected: just the picker")
        XCTAssertEqual(PictureChoices.plan([.change, .remove]), .menu([.change, .remove]))
        XCTAssertEqual(PictureChoices.plan([.change, .useInitials]), .menu([.change, .useInitials]))
        XCTAssertEqual(PictureChoices.plan([.change, .useDetected(.logo)]), .menu([.change, .useDetected(.logo)]))
    }

    /// The blue words under a page's name are gone (owner 2026-10-29): the source line says where the picture came
    /// from and carries no action.
    func testTheSourceLineCarriesNoAction() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/People/PersonHero.swift")
        let text = try String(contentsOf: file, encoding: .utf8)
        let line = try XCTUnwrap(text.range(of: "struct PictureSourceLine")).upperBound
        let next = text.range(of: "\nstruct ", range: line..<text.endIndex)?.lowerBound ?? text.endIndex
        let body = text[line..<next]
        XCTAssertFalse(body.contains("InlineLink"), "the picture's choices live on the picture, never as blue words")
        XCTAssertFalse(body.contains("PictureActions.run"))
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
