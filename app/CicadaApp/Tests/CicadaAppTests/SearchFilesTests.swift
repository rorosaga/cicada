import XCTest
@testable import CicadaApp

/// Search & files (owner, 2026-10-14) — *What Cicada can look through*: the section, the plain-words lint, the
/// `vision`/`part`/byte progress decoding, both consent rows in every state, and where folders now live.
final class SearchFilesTests: XCTestCase {
    static let small = "intfloat/multilingual-e5-small"
    static let sharper = "google/embeddinggemma-2:768"
    static let large = "google/embeddinggemma-300m"

    // MARK: The section

    func testTheSectionSitsBetweenPrivacyAndMemoryWithItsOwnPageTitle() {
        let cicada = SettingsGroup.cicada.sections
        XCTAssertEqual(cicada.firstIndex(of: .searchFiles), cicada.firstIndex(of: .privacy).map { $0 + 1 })
        XCTAssertEqual(cicada.firstIndex(of: .memory), cicada.firstIndex(of: .searchFiles).map { $0 + 1 })
        XCTAssertEqual(SettingsSection.searchFiles.title, "Search & files")
        XCTAssertEqual(SettingsSection.searchFiles.pageTitle, "What Cicada can look through")
        XCTAssertEqual(SettingsSection.memory.pageTitle, SettingsSection.memory.title, "other pages keep one name")
        XCTAssertEqual(SettingsSection.searchFiles.rawValue, "searchFiles", "a new case: no persisted value moves")
        XCTAssertEqual(SettingsSection.restored(from: "memory"), .memory)
        XCTAssertEqual(Copy.SearchFiles.pointer, "Settings → Search & files")
    }

    // MARK: The lint (the owner: "without mentioning embeddings")

    static let banned = ["model", "embedding", "index", "vector", "token", "runtime", "checksum"]

    private func assertPlain(_ text: String, file: StaticString = #filePath, line: UInt = #line) {
        let lower = text.lowercased()
        for word in Self.banned {
            XCTAssertFalse(lower.contains(word), "\"\(text)\" says \(word)", file: file, line: line)
        }
        for name in ["Neural Engine", "Gemma", "Google", "Core ML", "Hugging Face", "picture"] {
            XCTAssertFalse(text.contains(name), "\"\(text)\" says \(name)", file: file, line: line)
        }
    }

    func testDefaultVisibleWordsAreNeverTechnical() {
        XCTAssertGreaterThan(Copy.SearchFiles.defaultVisible.count, 50, "a lint over nothing passes vacuously")
        for text in Copy.SearchFiles.defaultVisible { assertPlain(text) }
        // The page's own section words, and what the moved folder rows say.
        for text in [SettingsSection.searchFiles.title, SettingsSection.searchFiles.pageTitle, SettingsSection.searchFiles.subtitle,
                     LocalSourceRowText.sleepLine(FolderSyncResult()), LocalSourceCopy.folderMissing,
                     LocalSourceCopy.folderPermissionFix, Copy.Folders.manageHelp, Copy.Folders.writtenByAnAgent,
                     Copy.Folders.writtenByAnAgentHelp, Copy.Folders.addTitle] {
            assertPlain(text)
        }
        // Every state either row can render, read off the logic rather than the copy table.
        for row in Self.everyRow() { assertPlain(row.detail); row.button.map { assertPlain($0) }; row.help.map { assertPlain($0) } }
    }

    func testAdvancedIsExemptButStillProviderNeutral() {
        // The version names and the rebuild live behind Advanced; the account sheet names the person's own account.
        for text in [Copy.SearchModel.title, Copy.SearchModel.pickerHelp, Copy.SearchModel.usesOther,
                     Copy.SearchModel.sheetTitle, Copy.SearchModel.installHelp, Copy.SearchFiles.rebuildTitle] {
            for name in ["Gemma", "Google", "Core ML", "Neural Engine"] { XCTAssertFalse(text.contains(name), text) }
        }
        XCTAssertTrue(Copy.SearchModel.sheetWhy.contains("Hugging Face"), "the account's site, named where it is used")
        XCTAssertTrue(Copy.SearchModel.sheetTokenUse.contains("isn't saved"))
    }

    func testTheHiddenSearchKeywordsAreKept() {
        let all = SettingsIndex.staticEntries + SettingsIndex.pageEntries
        let page = all.filter { $0.section == .searchFiles }
        let keywords = Set(page.flatMap(\.keywords))
        for kept in ["index", "model", "embedding", "embeddings", "semantic", "vectors", "rebuild", "search", "find"] {
            XCTAssertTrue(keywords.contains(kept), "\(kept) was a keyword of the old Memory rows")
        }
        XCTAssertEqual(SettingsIndex.search("embeddings", in: all).first?.entry.id, .searchMeaning)
        XCTAssertEqual(SettingsIndex.search("images", in: all).first?.entry.id, .searchImages)
        XCTAssertEqual(SettingsIndex.search("add a folder", in: all).first?.entry.id, .searchFolders)
        XCTAssertTrue(SettingsIndex.search("rebuild", in: all).contains { $0.entry.id == .searchIndex })
        XCTAssertTrue(SettingsIndex.search("look through", in: all).contains { $0.entry.id == .page(.searchFiles) },
                      "the page title finds the page")
        for id in [SettingsRowID.searchModel, .searchIndex] {
            XCTAssertEqual(SettingsIndex.entry(for: id, in: all)?.anchor, .searchAdvanced, "\(id.rawValue) opens Advanced")
        }
    }

    @MainActor
    func testAFolderIsIndexedOnSearchAndFilesAndOtherChannelsStayOnIntegrations() {
        let entries = SettingsIndex.dynamicEntries(
            channels: [SourceChannel(id: "folder:alpha-project-1a2b", label: "alpha-project", connected: true),
                       SourceChannel(id: "rss", label: "RSS", connected: true)],
            harnessRows: [], exportOnly: [], connections: [], agents: [])
        XCTAssertEqual(entries.first { $0.id == .channel("folder:alpha-project-1a2b") }?.section, .searchFiles)
        XCTAssertEqual(entries.first { $0.id == .channel("rss") }?.section, .integrations)
        XCTAssertEqual(ChannelActions.settingsSection(for: "folder:alpha-project-1a2b"), .searchFiles)
        XCTAssertEqual(ChannelActions.settingsSection(for: LocalSourceWatcher.wisprChannel), .integrations)
    }

    func testFoldersLeftIntegrationsAndThePointerMoved() throws {
        let source = try String(contentsOf: Self.source("Views/Settings/IntegrationsView.swift"), encoding: .utf8)
        XCTAssertFalse(source.contains("FolderChannelRow("), "folder rows render on Search & files only")
        XCTAssertFalse(source.contains("AddFolderRow.folder"), "Add a folder lives on Search & files")
        XCTAssertTrue(source.contains("AddFolderRow.obsidian"), "Obsidian stays in Integrations as an app entry")
        XCTAssertTrue(source.contains("FoldersPointerRow()"))
        XCTAssertTrue(LocalSourceCopy.folderNotSetUpHere.contains(Copy.SearchFiles.pointer))
        let page = try String(contentsOf: Self.source("Views/Settings/SearchFilesView.swift"), encoding: .utf8)
        XCTAssertTrue(page.contains("FolderChannelRow(channel:"))
        XCTAssertEqual(page.components(separatedBy: "PrimaryActionButton(").count - 1, 0,
                       "the page's one primary action is the empty state's Add a folder… (AddFolderRow.empty)")
    }

    func testTheMovedRowsFollowTheButtonAndColourRules() throws {
        let rows = try String(contentsOf: Self.source("Views/Settings/LocalSourceRows.swift"), encoding: .utf8)
        // DR-40: no system bordered styles on the folder rows, the add row or the manage sheet.
        let folderPart = rows.components(separatedBy: "/// G134 — Wispr Flow").first ?? rows
        XCTAssertFalse(folderPart.contains(".buttonStyle(.bordered)"))
        XCTAssertFalse(folderPart.contains(".buttonStyle(.borderedProminent)"))
        // DR-7: a failure is never drawn in danger.
        XCTAssertFalse(folderPart.contains("CicadaTheme.danger"))
        let sheet = try String(contentsOf: Self.source("Views/Settings/LargerSearchModelSheet.swift"), encoding: .utf8)
        XCTAssertFalse(sheet.contains("CicadaTheme.danger"))
    }

    static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }

    // MARK: Decoding

    func testDecodesVisionPartAndProgress() throws {
        let reply = Data("""
        {"model": "\(Self.small)", "nextModel": "\(Self.small)",
         "models": [{"id": "\(Self.sharper)", "label": "Sharper", "needsDownload": true, "needsToken": false,
                     "available": false, "downloadBytes": 585000000}],
         "install": {"state": "installing", "step": "Downloading — 12 of 309 MB", "part": "vision", "done": 12000000, "total": 309000000},
         "vision": {"supported": true, "installed": false, "downloadBytes": 894000000, "includesText": true}}
        """.utf8)
        let s = try JSONDecoder().decode(EmbeddingsStatus.self, from: reply)
        XCTAssertEqual(s.vision, EmbeddingVisionState(supported: true, installed: false, downloadBytes: 894_000_000, includesText: true))
        XCTAssertTrue(s.install.isVision)
        XCTAssertEqual(s.install.done, 12_000_000)
        XCTAssertEqual(s.install.total, 309_000_000)
        XCTAssertEqual(s.models.first?.downloadBytes, 585_000_000)
        let old = try JSONDecoder().decode(EmbeddingsStatus.self, from: Data(#"{"model": "x", "install": {"state": "installing"}}"#.utf8))
        XCTAssertNil(old.vision, "a backend that doesn't say gets no images row, never a guessed one")
        XCTAssertEqual(old.install.part, "")
        XCTAssertFalse(old.install.isVision, "an older backend's download is the meaning row's")
        XCTAssertNil(SearchUnderstanding.images(old))
    }

    func testLooksDecodesTheCombinedSize() throws {
        let v = try JSONDecoder().decode(DesignVision.self, from: Data(#"{"supported": true, "downloadBytes": 894000000, "includesText": true}"#.utf8))
        XCTAssertTrue(v.includesText)
        XCTAssertTrue(Copy.Looks.pictureDownload(v.downloadBytes, includesMeaning: true).contains("894 MB"))
        XCTAssertTrue(Copy.Looks.pictureDownload(v.downloadBytes, includesMeaning: true).contains("Understand what you mean"))
        XCTAssertFalse(Copy.Looks.pictureDownload(309_000_000).contains("Understand what you mean"))
        for text in [Copy.Looks.pictureOff, Copy.Looks.pictureUnsupported, Copy.Looks.pictureMissing] {
            XCTAssertFalse(text.lowercased().contains("model"), text)
            XCTAssertFalse(text.lowercased().contains("picture"), "images everywhere, Looks included: \(text)")
        }
    }

    // MARK: Understand what you mean

    private static func status(model: String = small, next: String? = nil, choice: String? = nil,
                               sharperAvailable: Bool = false, sharperOffered: Bool = true, largeOffered: Bool = false,
                               largeAvailable: Bool = false, install: EmbeddingInstallState = .init(),
                               reindex: EmbeddingReindexState = .init(), vision: EmbeddingVisionState? = nil) -> EmbeddingsStatus {
        var models = [EmbeddingModelOption(id: small, label: "Built in", needsDownload: false, available: true)]
        if sharperOffered {
            models.insert(EmbeddingModelOption(id: sharper, label: "Sharper", needsDownload: true, needsToken: false,
                                               available: sharperAvailable, downloadBytes: 585_000_000), at: 0)
        }
        if largeOffered {
            models.append(EmbeddingModelOption(id: large, label: "Larger", needsDownload: true, needsToken: true,
                                               available: largeAvailable))
        }
        return EmbeddingsStatus(model: model, nextModel: next ?? model, choice: choice, release: true,
                                recommended: sharperOffered && !sharperAvailable ? sharper : nil, models: models,
                                install: install, reindex: reindex, vision: vision)
    }

    func testTheOfferStatesTheSizeAndOneClickDownloadsThenSwitches() {
        let row = SearchUnderstanding.meaning(Self.status(), sleeping: false)
        XCTAssertEqual(row?.detail, Copy.SearchFiles.meaningOffer(bytes: 585_000_000))
        XCTAssertTrue(row?.detail.contains("585 MB") == true, "the size before the click")
        XCTAssertTrue(row?.detail.hasPrefix("On, built in.") == true, "meaning search already works built in")
        XCTAssertEqual(row?.button, Copy.SearchFiles.turnOn)
        XCTAssertEqual(row?.action, .fetchMeaning(Self.sharper))
        XCTAssertTrue(row?.enabled == true)
    }

    func testSleepRunningDimsTheButtonAndSaysWhy() {
        let row = SearchUnderstanding.meaning(Self.status(), sleeping: true)
        XCTAssertFalse(row?.enabled ?? true)
        XCTAssertEqual(row?.help, Copy.SearchFiles.sleepRunningHelp)
        XCTAssertEqual(row?.button, Copy.SearchFiles.turnOn, "the control keeps its label (DR-41)")
    }

    func testDownloadingShowsBytesThenSetup() {
        let streaming = EmbeddingInstallState(state: "installing", step: "Downloading — 312 of 585 MB", part: "text",
                                              done: 312_000_000, total: 585_000_000)
        let row = SearchUnderstanding.meaning(Self.status(install: streaming), sleeping: false)
        XCTAssertEqual(row?.detail, "Downloading — 312 of 585 MB. You can close Settings; it keeps going.")
        XCTAssertEqual(row?.total, 585_000_000)
        XCTAssertTrue(row?.busy == true)
        XCTAssertNil(row?.button, "no second click while the first runs")
        let settingUp = EmbeddingInstallState(state: "installing", step: "Setting up on this Mac — about a minute and a half, once", part: "text")
        XCTAssertEqual(SearchUnderstanding.meaning(Self.status(install: settingUp), sleeping: false)?.total, 0, "words, not a bar")
        let starting = EmbeddingInstallState(state: "installing", part: "text")
        XCTAssertEqual(SearchUnderstanding.meaning(Self.status(install: starting), sleeping: false)?.detail, Copy.SearchFiles.gettingReady)
    }

    func testAFailedDownloadOffersTryAgainWithTheBackendsSentence() {
        let failed = EmbeddingInstallState(state: "failed", error: "The download stopped. Check your connection and try again.", part: "text")
        let row = SearchUnderstanding.meaning(Self.status(install: failed), sleeping: false)
        XCTAssertTrue(row?.failed == true)
        XCTAssertEqual(row?.detail, failed.error)
        XCTAssertEqual(row?.button, Copy.SearchFiles.tryAgain)
        XCTAssertEqual(row?.action, .fetchMeaning(Self.sharper))
        let fixed = SearchUnderstanding.meaning(Self.status(model: Self.sharper, sharperAvailable: true, install: failed), sleeping: false)
        XCTAssertFalse(fixed?.failed ?? true, "a failure a later download fixed is not shown")
        let imageFailure = EmbeddingInstallState(state: "failed", error: "x", part: "vision")
        XCTAssertFalse(SearchUnderstanding.meaning(Self.status(install: imageFailure), sleeping: false)?.failed ?? true,
                       "the image part's failure is the images row's")
    }

    func testTheReReadAndThePendingSwitchSayThatSearchKeepsWorking() {
        let running = EmbeddingReindexState(state: "running", model: Self.sharper, done: 1, total: 3)
        let row = SearchUnderstanding.meaning(Self.status(next: Self.sharper, sharperAvailable: true, reindex: running), sleeping: false)
        XCTAssertEqual(row?.detail, "Re-reading your memory for sharper matches — step 1 of 3. Search keeps working meanwhile.")
        let waiting = EmbeddingReindexState(state: "waiting", model: Self.sharper)
        XCTAssertEqual(SearchUnderstanding.meaning(Self.status(next: Self.sharper, sharperAvailable: true, reindex: waiting), sleeping: true)?.detail,
                       Copy.SearchFiles.waitsForSleep)
        XCTAssertEqual(SearchUnderstanding.meaning(Self.status(next: Self.sharper, sharperAvailable: true), sleeping: false)?.detail,
                       Copy.SearchFiles.switchesAtNextSleep)
        let failed = EmbeddingReindexState(state: "failed", model: Self.sharper, error: "Search couldn't switch, so it keeps working as before.")
        XCTAssertTrue(SearchUnderstanding.meaning(Self.status(next: Self.sharper, sharperAvailable: true, reindex: failed), sleeping: false)?.failed == true)
    }

    func testReadyStatesSayOn() {
        let sharper = SearchUnderstanding.meaning(Self.status(model: Self.sharper, sharperAvailable: true), sleeping: false)
        XCTAssertEqual(sharper?.detail, Copy.SearchFiles.meaningSharper)
        XCTAssertTrue(sharper?.on == true)
        XCTAssertNil(sharper?.button)
        let builtInOnly = SearchUnderstanding.meaning(Self.status(sharperOffered: false), sleeping: false)
        XCTAssertEqual(builtInOnly?.detail, Copy.SearchFiles.meaningBuiltIn, "a Mac that can't run the sharper version")
        XCTAssertTrue(builtInOnly?.on == true)
        let larger = SearchUnderstanding.meaning(Self.status(model: Self.large, sharperOffered: false, largeOffered: true,
                                                             largeAvailable: true), sleeping: false)
        XCTAssertEqual(larger?.detail, Copy.SearchFiles.meaningLarger)
        XCTAssertEqual(SearchUnderstanding.meaning(Self.status(model: "some/other"), sleeping: false)?.detail, Copy.SearchFiles.meaningOther)
    }

    func testTheSharperVersionHereButUnusedIsOneClickToUse() {
        let row = SearchUnderstanding.meaning(Self.status(choice: Self.small, sharperAvailable: true), sleeping: false)
        XCTAssertEqual(row?.detail, Copy.SearchFiles.meaningReadyHere)
        XCTAssertEqual(row?.action, .chooseMeaning(Self.sharper))
    }

    func testAMemoryBuiltElsewhereSaysSearchUsesWordsUntilTheDownload() {
        let row = SearchUnderstanding.meaning(Self.status(model: Self.sharper), sleeping: false)
        XCTAssertEqual(row?.detail, Copy.SearchFiles.meaningMissing(bytes: 585_000_000))
        XCTAssertEqual(row?.button, Copy.SearchFiles.download)
        XCTAssertEqual(row?.action, .fetchMeaning(Self.sharper))
        let larger = SearchUnderstanding.meaning(Self.status(model: Self.large, sharperOffered: false, largeOffered: true), sleeping: false)
        XCTAssertEqual(larger?.detail, Copy.SearchFiles.meaningMissingLarger)
        XCTAssertNil(larger?.button, "the larger version needs the account sheet, under Advanced")
    }

    // MARK: Review fixes (B1, B2 and the 409)

    /// B1 — selecting a not-installed option never calls install: the pick only raises a confirm that names the size,
    /// and the one `installEmbeddingModel` in the picker's path is behind the confirm's explicit Download.
    func testSelectingANotInstalledVersionDoesNotDownload() throws {
        let status = Self.status()
        XCTAssertEqual(SearchModelLogic.route(picked: Self.sharper, status: status, sleepWriting: false), .confirmDownload(Self.sharper))
        let confirm = SearchModelLogic.confirmation(for: Self.sharper, in: status)
        XCTAssertTrue(confirm.contains("585 MB"), "the size before the click: \(confirm)")
        XCTAssertFalse(Copy.SearchModel.usesNowBetterHere("Built in", better: "Sharper").contains("download it once"))
        let page = try String(contentsOf: Self.source("Views/Settings/SearchFilesView.swift"), encoding: .utf8)
        let pick = try XCTUnwrap(page.components(separatedBy: "private func pick(").dropFirst().first?
            .components(separatedBy: "private func confirmDownload(").first)
        XCTAssertFalse(pick.contains("installEmbeddingModel"), "a pick sends no install request")
        XCTAssertTrue(pick.contains("pendingDownload = id"))
        let confirmBody = try XCTUnwrap(page.components(separatedBy: "private func confirmDownload(").dropFirst().first?
            .components(separatedBy: "private func send(").first)
        XCTAssertTrue(confirmBody.contains("installEmbeddingModel"), "only the explicit Download sends it")
    }

    /// B2 — a failed re-read on the default view is the page's own sentence, whatever the backend's diagnostic said.
    func testAFailedReReadIsSaidInThePagesOwnWords() {
        let diagnostic = EmbeddingReindexState(state: "failed", model: Self.sharper,
                                               error: "the search model this memory uses isn't installed; run `make embedding-model`")
        let row = SearchUnderstanding.meaning(Self.status(next: Self.sharper, sharperAvailable: true, reindex: diagnostic), sleeping: false)
        XCTAssertEqual(row?.detail, Copy.SearchFiles.rereadFailed)
        XCTAssertTrue(row?.failed == true)
    }

    /// While the image download runs (or the Looks shortcut fetches both), Turn on is dimmed with the reason, not a 409.
    func testTurnOnWaitsWhileAnyDownloadRuns() {
        let vision = EmbeddingInstallState(state: "installing", step: "Downloading — 1 of 894 MB", part: "vision", done: 1, total: 894)
        let row = SearchUnderstanding.meaning(Self.status(install: vision), sleeping: false)
        XCTAssertEqual(row?.button, Copy.SearchFiles.turnOn)
        XCTAssertFalse(row?.enabled ?? true)
        XCTAssertEqual(row?.help, Copy.SearchFiles.downloadRunningHelp)
    }

    // MARK: Understand images

    func testImagesWaitForMeaningSoTheTwoClicksStayTwo() {
        let vision = EmbeddingVisionState(supported: true, installed: false, downloadBytes: 894_000_000, includesText: true)
        let row = SearchUnderstanding.images(Self.status(vision: vision))
        XCTAssertEqual(row?.detail, Copy.SearchFiles.imagesWaitsForMeaning)
        XCTAssertFalse(row?.enabled ?? true)
        XCTAssertEqual(row?.help, Copy.SearchFiles.imagesWaitsHelp)
        XCTAssertEqual(row?.button, Copy.SearchFiles.turnOn, "dimmed at 45 %, label kept (DR-41)")
    }

    func testImagesOfferTheirOwnSizeOnceMeaningIsHere() {
        let vision = EmbeddingVisionState(supported: true, installed: false, downloadBytes: 309_000_000, includesText: false)
        let row = SearchUnderstanding.images(Self.status(model: Self.sharper, sharperAvailable: true, vision: vision))
        XCTAssertEqual(row?.detail, Copy.SearchFiles.imagesOffer(bytes: 309_000_000))
        XCTAssertTrue(row?.detail.contains("309 MB") == true)
        XCTAssertEqual(row?.action, .fetchImages)
        XCTAssertTrue(row?.enabled == true)
        XCTAssertTrue(SearchUnderstanding.images(Self.status(model: Self.sharper, sharperAvailable: true, vision: vision))?.enabled == true)
    }

    func testImagesWhileAnotherDownloadRunsAndWhileTheirOwnRuns() {
        let vision = EmbeddingVisionState(supported: true, downloadBytes: 309_000_000)
        let text = EmbeddingInstallState(state: "installing", step: "Downloading — 1 of 585 MB", part: "text", done: 1, total: 585)
        let waiting = SearchUnderstanding.images(Self.status(install: text, vision: vision))
        XCTAssertEqual(waiting?.detail, Copy.SearchFiles.imagesWaitsForDownload)
        XCTAssertFalse(waiting?.enabled ?? true)
        let own = EmbeddingInstallState(state: "installing", step: "Downloading — 100 of 309 MB", part: "vision", done: 100, total: 309)
        let row = SearchUnderstanding.images(Self.status(model: Self.sharper, sharperAvailable: true, install: own, vision: vision))
        XCTAssertTrue(row?.busy == true)
        XCTAssertEqual(row?.total, 309)
        let meaning = SearchUnderstanding.meaning(Self.status(model: Self.sharper, sharperAvailable: true, install: own), sleeping: false)
        XCTAssertEqual(meaning?.total, 0, "the image download never shows on the meaning row")
        XCTAssertFalse(meaning?.busy ?? true)
    }

    func testImagesOnUnsupportedAndFailed() {
        let unsupported = SearchUnderstanding.images(Self.status(vision: EmbeddingVisionState(supported: false)))
        XCTAssertEqual(unsupported?.detail, Copy.SearchFiles.imagesUnsupported)
        XCTAssertNil(unsupported?.button, "nothing to retry on an unsupported Mac")
        let on = SearchUnderstanding.images(Self.status(vision: EmbeddingVisionState(supported: true, installed: true)))
        XCTAssertTrue(on?.on == true)
        XCTAssertEqual(on?.detail, Copy.SearchFiles.imagesOn)
        let failed = EmbeddingInstallState(state: "failed", error: "Something in the download didn't check out, so nothing was installed.",
                                           part: "vision")
        let row = SearchUnderstanding.images(Self.status(model: Self.sharper, sharperAvailable: true, install: failed,
                                                         vision: EmbeddingVisionState(supported: true, downloadBytes: 309)))
        XCTAssertTrue(row?.failed == true)
        XCTAssertEqual(row?.button, Copy.SearchFiles.tryAgain)
    }

    /// Every row state above, for the lint.
    static func everyRow() -> [UnderstandRow] {
        let installs: [EmbeddingInstallState] = [
            .init(), .init(state: "installing", step: "Downloading — 1 of 2 MB", part: "text", done: 1, total: 2),
            .init(state: "installing", part: "vision"), .init(state: "failed", error: "The download stopped.", part: "text"),
            .init(state: "failed", error: "The download stopped.", part: "vision"),
        ]
        let reindexes: [EmbeddingReindexState] = [.init(), .init(state: "running", done: 1, total: 3), .init(state: "waiting")]
        let visions: [EmbeddingVisionState] = [.init(supported: false), .init(supported: true, downloadBytes: 309),
                                               .init(supported: true, installed: true),
                                               .init(supported: true, downloadBytes: 894, includesText: true)]
        var rows: [UnderstandRow] = []
        for install in installs {
            for reindex in reindexes {
                for vision in visions {
                    for (model, available) in [(small, false), (small, true), (sharper, true), (sharper, false), ("x", false)] {
                        let s = status(model: model, sharperAvailable: available, install: install, reindex: reindex, vision: vision)
                        rows += [SearchUnderstanding.meaning(s, sleeping: false), SearchUnderstanding.meaning(s, sleeping: true),
                                 SearchUnderstanding.images(s)].compactMap { $0 }
                    }
                }
            }
        }
        return rows
    }

    // MARK: Folder rows

    func testAFolderRowSaysItsNotesAndWhenItWasRead() {
        let en = Locale(identifier: "en_US")
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let channel = SourceChannel(id: "folder:alpha-1", label: "alpha", connected: true, count: 1_312,
                                    lastSync: ISO8601DateFormatter().string(from: now.addingTimeInterval(-7_200)))
        let line = LocalSourceRowText.folderState(channel, onThisMac: true, reading: false, now: now, locale: en)
        XCTAssertTrue(line.hasPrefix("1,312 notes · "), line)
        XCTAssertEqual(LocalSourceRowText.folderState(channel, onThisMac: false, reading: false, now: now, locale: en),
                       LocalSourceCopy.folderMissing)
        XCTAssertEqual(LocalSourceRowText.folderState(channel, onThisMac: true, reading: true, now: now, locale: en),
                       Copy.SearchFiles.readingNow)
        let fresh = SourceChannel(id: "folder:beta-2", label: "beta", connected: false)
        XCTAssertEqual(LocalSourceRowText.folderState(fresh, onThisMac: true, reading: false, now: now, locale: en),
                       Copy.SearchFiles.notReadYet)
    }
}
