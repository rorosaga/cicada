import XCTest
@testable import CicadaApp

/// G133 / G134 surfaces — categories, marks, names, kinds, light copy and the
/// rows' sentences (R-LS25 … R-LS27).
final class LocalSourcesSurfaceTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testFoldersAndNotesLiveUnderNotesAndFilesAndWisprUnderVoice() {
        XCTAssertEqual(IntegrationCategory.of(channelId: "folder:alpha-project-1a2b3c"), .notesAndFiles)
        XCTAssertEqual(IntegrationCategory.of(channelId: "notes"), .notesAndFiles)
        XCTAssertEqual(IntegrationCategory.of(channelId: "wispr-flow"), .voiceAndMeetings)
        XCTAssertEqual(IntegrationCategory.of(channelId: "files"), .filesAndImports)
        XCTAssertEqual(IntegrationCategory.notesAndFiles.title, "Notes & files")
        XCTAssertEqual(IntegrationCategory.voiceAndMeetings.title, "Voice & meetings")
    }

    func testMarksResolveThroughTheInstalledAppFirst() {
        XCTAssertEqual(OriginIconography.appBundleId(for: "wispr-flow"), "com.electron.wispr-flow")
        XCTAssertEqual(OriginIconography.appBundleId(for: "obsidian"), "md.obsidian")
        XCTAssertEqual(OriginIconography.label(for: "wispr-flow"), "Wispr Flow")
        XCTAssertEqual(OriginIconography.symbol(for: "wispr-flow"), "waveform")
        XCTAssertEqual(OriginIconography.symbol(for: "folder"), "folder")
        XCTAssertTrue(OriginIconography.allKnownOrigins.contains("folder"))
        XCTAssertTrue(OriginIconography.allKnownOrigins.contains("wispr-flow"))
        XCTAssertEqual(ConnectedChannelRow.origin(forChannel: "folder:alpha-project-1a2b3c"), "folder")
        XCTAssertEqual(ConnectedChannelRow.icon(for: "folder:alpha-project-1a2b3c"), "folder")
        XCTAssertEqual(ConnectedChannelRow.icon(for: "wispr-flow"), "waveform")
    }

    func testAFolderCardIsNamedByThePersonAndWisprByItsBrand() {
        let folder = SourceOverview(id: "folder:alpha-project-1a2b3c", label: "alpha-project", kind: .import)
        XCTAssertEqual(SourceDisplayName.of(folder), "alpha-project")
        XCTAssertEqual(SourceDisplayName.of(id: "wispr-flow"), "Wispr Flow")
        XCTAssertEqual(SourceBlurb.text(for: folder), "Notes in alpha-project, kept in step as you edit them.")
    }

    func testTheVoiceKindDecodesAndHasItsOwnSection() throws {
        let json = #"{"id": "wispr-flow", "label": "Wispr Flow", "kind": "voice", "episodes": 2}"#
        let row = try JSONDecoder().decode(SourceOverview.self, from: Data(json.utf8))
        XCTAssertEqual(row.kind, .voice)
        XCTAssertEqual(SourceSections.group([row]).first?.title, "VOICE & MEETINGS")
        XCTAssertEqual(SourceKind.order.firstIndex(of: .voice), SourceKind.order.firstIndex(of: .import).map { $0 - 1 })
    }

    func testLocalLightsExplainThemselvesInTheirOwnWords() {
        let browser = BrowserStatusLight.explanation(for: .watching)
        let folder = BrowserStatusLight.explanation(for: .watching, channelId: "folder:alpha-1")
        let wispr = BrowserStatusLight.explanation(for: .watching, channelId: "wispr-flow")
        XCTAssertNotEqual(folder, browser)
        XCTAssertNotEqual(wispr, browser)
        XCTAssertFalse(folder.contains("bookmark"))
        XCTAssertEqual(BrowserStatusLight.explanation(for: .stale, channelId: nil), BrowserStatusLight.explanation(for: .stale))
    }

    func testTheAddFolderSheetSaysCountsInPlainWords() {
        var r = FolderSyncResult()
        r.filesNew = 12
        r.agentFiles = 3
        r.papersFound = 1_200
        r.stage1Passes = 7
        // Synthetic counts; 1,200 also proves the number is grouped for the reader's locale.
        XCTAssertEqual(LocalSourceRowText.previewSummary(r, locale: en), "Found 12 notes · 3 written by an agent · 1,200 papers")
        XCTAssertEqual(LocalSourceRowText.sleepLine(r, locale: en), "Sleep will read your own notes in about 7 steps.")
        var one = FolderSyncResult()
        one.filesNew = 1
        XCTAssertEqual(LocalSourceRowText.previewSummary(one, locale: en), "Found 1 note")
        XCTAssertTrue(LocalSourceRowText.sleepLine(one, locale: en).hasPrefix("Nothing here for Sleep"))
        XCTAssertEqual(LocalSourceRowText.list("archive/**, drafts/**\nold/**"), ["archive/**", "drafts/**", "old/**"])
    }

    func testTheWisprLineBeforeAndAfterItIsOn() {
        XCTAssertEqual(LocalSourceRowText.wisprLine(nil, settings: WisprFlowSettings()),
                       "Your meetings and notes from Wispr Flow on this Mac.")
        XCTAssertEqual(LocalSourceRowText.wisprLine(nil, settings: WisprFlowSettings(enabled: true)),
                       "On — the first sync is on its way")
    }
}
