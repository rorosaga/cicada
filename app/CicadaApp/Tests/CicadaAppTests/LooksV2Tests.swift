import XCTest
@testable import CicadaApp

/// Looks v2 (2026-10-15) — whose words a note is, the page's type and colour roles on the wire, the strip that no
/// longer hides the ink, and "Save its look". Synthetic only; a fake API, nothing reaches a backend or the clipboard.
@MainActor
final class LooksV2Tests: XCTestCase {
    static let refJSON = """
    {"id": "2026-10-15-ink-example-com", "title": "Ink", "site": "ink.example.com", "addedBy": "claude-code",
     "addedByKind": "harness", "via": "agent", "noteBy": "claude-code", "noteByKind": "harness",
     "notePreview": "One cobalt ink on off-white.", "note": "One cobalt ink on off-white.",
     "palette": [{"hex": "#fafafb", "share": 0.9, "role": "ground"},
                 {"hex": "#1342ff", "share": 0.004, "role": "accent", "declared": true}],
     "typeRoles": [{"role": "body", "family": "Newsreader", "generic": "serif", "size": 19, "weight": 400,
                    "lineHeight": 30.4, "letterSpacing": 0, "color": "#1342ff"},
                   {"role": "drop_cap", "family": "Newsreader", "size": 88}],
     "colourRoles": [{"role": "ground", "hex": "#fafafb", "source": "page"},
                     {"role": "wash", "hex": "#dde3f8", "source": "pixels"}]}
    """

    func testAnAgentsNoteIsShownAsItsOwnNeverWhatYouLiked() throws {
        let ref = try JSONDecoder().decode(DesignRef.self, from: Data(Self.refJSON.utf8))
        XCTAssertFalse(ref.summary.noteIsTheirs)
        XCTAssertEqual(LooksNote.heading(ref.summary), "Noted by Claude Code")
        XCTAssertEqual(LooksNote.text(summary: ref.summary, detail: ref), "One cobalt ink on off-white.")
        let mine = DesignRefSummary(id: "a", notePreview: "Calm cards.")
        XCTAssertTrue(mine.noteIsTheirs)
        XCTAssertEqual(LooksNote.heading(mine), Copy.Looks.liked)
        XCTAssertNil(LooksNote.heading(DesignRefSummary(id: "b", addedBy: "codex")), "an agent's empty note: no section")
    }

    func testAnOlderServersAgentSaveIsStillNotThePersonsWords() {
        let rest = DesignRefSummary(id: "c", addedBy: "user", via: "agent", notePreview: "Noted while browsing.")
        XCTAssertEqual(rest.noteBy, "agent")
        XCTAssertEqual(LooksNote.heading(rest), "Noted by an agent")
        XCTAssertEqual(DesignRefSummary(id: "d", addedBy: "claude-code", via: "explore").noteBy, "user",
                       "an explore Look's note is the person's saved reason")
    }

    func testTheTypeAndColourRolesDecode() throws {
        let ref = try JSONDecoder().decode(DesignRef.self, from: Data(Self.refJSON.utf8))
        XCTAssertEqual(ref.typeRoles.map(\.role), ["body", "drop_cap"])
        XCTAssertEqual(ref.typeRoles[0].lineHeight, 30.4)
        XCTAssertEqual(Copy.Looks.typeDetail(size: 19, weight: 400, lineHeight: 30.4), "19 px · 400 · 30.4 px leading")
        XCTAssertEqual(Copy.Looks.typeRole("drop_cap"), "Drop cap")
        XCTAssertEqual(ref.colourRoles.last, DesignColourRole(role: "wash", hex: "#dde3f8", source: "pixels"))
        XCTAssertEqual(ref.summary.palette[1].role, "accent")
        XCTAssertEqual(ref.summary.palette[1].declared, true)
        let old = try JSONDecoder().decode(DesignRef.self, from: Data(#"{"id": "x"}"#.utf8))
        XCTAssertTrue(old.typeRoles.isEmpty && old.colourRoles.isEmpty, "an older server sends neither")
    }

    func testTheStripGivesTheGroundHalfAndTheAccentsTheRest() {
        let colours = [DesignColour(hex: "#fafafb", share: 0.9), DesignColour(hex: "#1342ff", share: 0.004),
                       DesignColour(hex: "#dde3f8", share: 0.05)]
        XCTAssertEqual(LooksPaletteStrip.widths(colours, total: 64), [32, 16, 16],
                       "a 0.4 % ink is a quarter of the strip, not a hairline")
        XCTAssertEqual(LooksPaletteStrip.widths([colours[0]], total: 64), [64])
    }

    func testSaveItsLookQueuesAndHandsBackThePrompt() async {
        let api = ExploreTests.FakeAPI()
        let ok = await SaveLook.run(mediaEntityId: "media-ink", url: "https://ink.example.com/", api: api)
        XCTAssertEqual(ok, .queued(prompt: "Explore 1 of my saved sites…"))
        XCTAssertEqual(api.looks.first?.0, "media-ink")
        api.lookError = APIError.httpError(422, #"{"detail": "That link can't be explored."}"#)
        let refused = await SaveLook.run(mediaEntityId: "media-ink", url: "https://ink.example.com/", api: api)
        XCTAssertEqual(refused, .failed("That link can't be explored."))
        api.lookError = URLError(.notConnectedToInternet)
        let down = await SaveLook.run(mediaEntityId: "media-ink", url: "https://ink.example.com/", api: api)
        XCTAssertEqual(down, .failed(Copy.Looks.saveLookFailed))
    }
}
