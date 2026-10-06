import XCTest
@testable import CicadaApp

/// G182 phase 3 — Settings → Memory → Search model: the wire, the token's one road out, the
/// detail line in words and the pick routing.
final class SearchModelTests: XCTestCase {
    static let small = "BAAI/bge-small-en-v1.5"
    static let large = "google/embeddinggemma-300m"
    static let token = "hf_exampleTokenValue1234567890"

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private func status(model: String = small, next: String? = nil, largeAvailable: Bool = false,
                        install: EmbeddingInstallState = EmbeddingInstallState()) -> EmbeddingsStatus {
        EmbeddingsStatus(model: model, nextModel: next ?? model, choice: nil, release: true, models: [
            EmbeddingModelOption(id: Self.small, label: "Small", dimensions: 384,
                                 detail: "Built in. Quick, and good for most memories.", needsDownload: false, available: true),
            EmbeddingModelOption(id: Self.large, label: "Larger", dimensions: 768,
                                 detail: "Finds looser matches.", needsDownload: true, available: largeAvailable),
        ], install: install)
    }

    private static let reply = """
    {"model": "BAAI/bge-small-en-v1.5", "nextModel": "google/embeddinggemma-300m", "choice": "google/embeddinggemma-300m",
     "release": true,
     "models": [
       {"id": "BAAI/bge-small-en-v1.5", "label": "Small", "dimensions": 384, "detail": "Built in.", "needsDownload": false, "available": true},
       {"id": "google/embeddinggemma-300m", "label": "Larger", "dimensions": 768, "detail": "About 2 GB.", "needsDownload": true, "available": false}
     ],
     "install": {"state": "installing", "step": "Downloading the model (about 1.2 GB)", "error": ""}}
    """.data(using: .utf8)!

    private static func body(_ request: URLRequest) -> Data {
        request.httpBodyStream.map { stream -> Data in
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: 1024)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        } ?? request.httpBody ?? Data()
    }

    private static func ok(_ request: URLRequest, status: Int = 200, data: Data = reply) -> (HTTPURLResponse, Data) {
        (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, data)
    }

    // MARK: Decoding

    func testDecodesTheCamelCaseWire() throws {
        let s = try JSONDecoder().decode(EmbeddingsStatus.self, from: Self.reply)
        XCTAssertEqual(s.model, Self.small)
        XCTAssertEqual(s.nextModel, Self.large)
        XCTAssertEqual(s.choice, Self.large)
        XCTAssertTrue(s.release)
        XCTAssertEqual(s.models.map(\.label), ["Small", "Larger"])
        XCTAssertEqual(s.models[1].dimensions, 768)
        XCTAssertTrue(s.models[1].needsDownload)
        XCTAssertFalse(s.models[1].available)
        XCTAssertEqual(s.downloadable?.id, Self.large)
        XCTAssertTrue(s.install.isInstalling)
        XCTAssertEqual(s.install.step, "Downloading the model (about 1.2 GB)")
    }

    func testAnOlderOrSparserReplyStillDecodes() throws {
        let s = try JSONDecoder().decode(EmbeddingsStatus.self, from: Data(#"{"model": "x", "choice": null}"#.utf8))
        XCTAssertEqual(s.nextModel, "x", "a missing nextModel means nothing is pending")
        XCTAssertNil(s.choice)
        XCTAssertEqual(s.models, [])
        XCTAssertEqual(s.install.state, "idle")
    }

    // MARK: APIClient

    func testFetchEmbeddingsIsAGet() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/embeddings")
            return Self.ok(request)
        }
        let s = try await APIClient(session: MockURLProtocol.makeSession()).fetchEmbeddings()
        XCTAssertEqual(s.nextModel, Self.large)
    }

    func testChooseSendsTheIdAndNilSendsNull() async throws {
        var bodies: [[String: Any]] = []
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/embeddings/choice")
            bodies.append((try? JSONSerialization.jsonObject(with: Self.body(request)) as? [String: Any]) ?? [:])
            return Self.ok(request)
        }
        let client = APIClient(session: MockURLProtocol.makeSession())
        _ = try await client.chooseEmbeddingModel(Self.large)
        _ = try await client.chooseEmbeddingModel(nil)
        XCTAssertEqual(bodies.count, 2)
        XCTAssertEqual(bodies[0]["model"] as? String, Self.large)
        XCTAssertTrue(bodies[1]["model"] is NSNull, "nil goes back to the default as JSON null")
    }

    func testChoose409CarriesTheBackendsSentence() async {
        MockURLProtocol.handler = { request in
            Self.ok(request, status: 409, data: Data(#"{"detail": "Sleep is running; change the search model when it finishes."}"#.utf8))
        }
        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession()).chooseEmbeddingModel(Self.small)
            XCTFail("a 409 throws")
        } catch {
            XCTAssertEqual(AddSourceSheet.friendlyError(error), "Sleep is running; change the search model when it finishes.")
        }
    }

    func testTheTokenRidesOnlyThePostBodyAndIsNotKept() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/embeddings/install")
            XCTAssertFalse(request.url?.absoluteString.contains(Self.token) ?? true, "never in the URL")
            for (_, value) in request.allHTTPHeaderFields ?? [:] {
                XCTAssertFalse(value.contains(Self.token), "never in a header")
            }
            let object = try JSONSerialization.jsonObject(with: Self.body(request)) as? [String: Any]
            XCTAssertEqual(object?.keys.sorted(), ["hfToken"], "the body carries the token and nothing else")
            XCTAssertEqual(object?["hfToken"] as? String, Self.token)
            return Self.ok(request, status: 202)
        }
        let s = try await APIClient(session: MockURLProtocol.makeSession()).installLargerEmbeddingModel(token: Self.token)
        XCTAssertTrue(s.install.isInstalling)
        let stored = UserDefaults.standard.dictionaryRepresentation().values.contains { "\($0)".contains(Self.token) }
        XCTAssertFalse(stored, "the token is never written to UserDefaults")
    }

    /// The sheet and the wire never store or log anything (code lines only; a doc comment may say so).
    func testTheSheetAndTheWireNeverPersistOrLog() throws {
        let files = try ThemeTokenTests.swiftSources().filter {
            $0.lastPathComponent == "LargerSearchModelSheet.swift" || $0.lastPathComponent == "EmbeddingsWire.swift"
        }
        XCTAssertEqual(files.count, 2)
        for file in files {
            let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
                .joined(separator: "\n")
            for needle in ["UserDefaults", "@AppStorage", "SecItemAdd", "Keychain", "print(", "Logger(", "os_log", "NSLog("] {
                XCTAssertFalse(code.contains(needle), "\(file.lastPathComponent) mentions \(needle)")
            }
        }
    }

    // MARK: The detail line

    func testDetailWhatTheBankUsesNow() {
        XCTAssertNil(SearchModelLogic.detail(nil))
        XCTAssertEqual(SearchModelLogic.detail(status()),
                       "Searching with the Small model. Built in. Quick, and good for most memories.")
        XCTAssertEqual(SearchModelLogic.detail(status(model: "some/other-model")),
                       "Searching with another model set up on this Mac.")
    }

    func testDetailAfterAChange() {
        XCTAssertEqual(SearchModelLogic.detail(status(next: Self.large, largeAvailable: true)),
                       "Search switches to Larger at the next Sleep, which re-reads this memory once.")
    }

    func testDetailWhileInstallingAndAfter() {
        XCTAssertEqual(SearchModelLogic.detail(status(install: .init(state: "installing", step: "Preparing"))), "Preparing…")
        XCTAssertEqual(SearchModelLogic.detail(status(install: .init(state: "installing"))), "Installing the larger model…")
        XCTAssertEqual(SearchModelLogic.detail(status(largeAvailable: true, install: .init(state: "done"))),
                       "Larger is ready on this Mac — choose it to switch.")
        XCTAssertEqual(SearchModelLogic.detail(status(model: Self.large, largeAvailable: true, install: .init(state: "done"))),
                       "Searching with the Larger model. Finds looser matches.", "once chosen, done is quiet")
    }

    func testDetailAfterAFailure() {
        let failed = EmbeddingInstallState(state: "failed", error: "The download stopped: 401")
        XCTAssertEqual(SearchModelLogic.detail(status(install: failed)), "The download stopped: 401")
        XCTAssertEqual(SearchModelLogic.detail(status(largeAvailable: true, install: failed)),
                       "Searching with the Small model. Built in. Quick, and good for most memories.",
                       "a failure that a later install fixed is not shown")
    }

    func testDetailNamesNoProvider() {
        let lines = [status(), status(next: Self.large, largeAvailable: true),
                     status(install: .init(state: "installing")), status(largeAvailable: true, install: .init(state: "done"))]
            .compactMap { SearchModelLogic.detail($0) }
        for line in lines {
            for name in ["Hugging Face", "Google", "BAAI", "Gemma", "bge"] {
                XCTAssertFalse(line.contains(name), "\(line) names \(name)")
            }
        }
    }

    // MARK: Routing a pick

    func testPickingAnUnavailableModelOpensTheSheet() {
        XCTAssertEqual(SearchModelLogic.route(picked: Self.large, status: status(), sleepWriting: false), .install)
    }

    func testPickingAnAvailableModelChoosesIt() {
        XCTAssertEqual(SearchModelLogic.route(picked: Self.large, status: status(largeAvailable: true), sleepWriting: false),
                       .choose(Self.large))
        XCTAssertEqual(SearchModelLogic.route(picked: Self.small, status: status(next: Self.large, largeAvailable: true),
                                              sleepWriting: false), .choose(Self.small), "a pending change can be undone")
    }

    func testPickingTheCurrentModelOrDuringAnInstallDoesNothing() {
        XCTAssertEqual(SearchModelLogic.route(picked: Self.small, status: status(), sleepWriting: false), .nothing)
        XCTAssertEqual(SearchModelLogic.route(picked: Self.large, status: status(install: .init(state: "installing")),
                                              sleepWriting: false), .nothing)
        XCTAssertEqual(SearchModelLogic.route(picked: "unknown/model", status: status(), sleepWriting: false), .nothing)
    }

    func testPickingWhileSleepWritesIsBlocked() {
        XCTAssertEqual(SearchModelLogic.route(picked: Self.large, status: status(largeAvailable: true), sleepWriting: true), .blocked)
        XCTAssertEqual(SearchModelLogic.route(picked: Self.large, status: status(), sleepWriting: true), .blocked)
    }

    func testTokenShapeAndPages() {
        XCTAssertTrue(SearchModelLogic.tokenLooksValid("hf_abc"))
        XCTAssertTrue(SearchModelLogic.tokenLooksValid("  hf_abc \n"))
        XCTAssertFalse(SearchModelLogic.tokenLooksValid(""))
        XCTAssertFalse(SearchModelLogic.tokenLooksValid("abc_hf"))
        XCTAssertEqual(SearchModelLogic.modelPage(Self.large)?.absoluteString, "https://huggingface.co/google/embeddinggemma-300m")
        XCTAssertEqual(SearchModelLogic.tokensPage.absoluteString, "https://huggingface.co/settings/tokens")
    }

    // MARK: The Settings index

    func testTheRowIsIndexedOnMemory() {
        let entry = SettingsIndex.staticEntries.first { $0.id == .searchModel }
        XCTAssertEqual(entry?.section, .memory)
        XCTAssertEqual(entry?.title, Copy.SearchModel.title)
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.searchModel))
        let all = SettingsIndex.staticEntries + SettingsIndex.pageEntries
        for query in ["embedding", "semantic", "meaning"] {
            XCTAssertEqual(SettingsIndex.search(query, in: all).first?.entry.id, .searchModel, query)
        }
        XCTAssertTrue(SettingsIndex.search("larger", in: all).contains { $0.entry.id == .searchModel })
    }

    func testTheSheetCopyExplainsTheTokenAndNamesOnlyTheAccountsHost() {
        XCTAssertTrue(Copy.SearchModel.sheetWhy.contains("license"))
        XCTAssertTrue(Copy.SearchModel.sheetWhy.contains("your own read-access token"))
        XCTAssertTrue(Copy.SearchModel.sheetTokenUse.contains("isn't saved"))
        XCTAssertTrue(Copy.SearchModel.sheetTokenUse.contains("2 GB"))
        for text in [Copy.SearchModel.sheetWhy, Copy.SearchModel.sheetTokenUse, Copy.SearchModel.title,
                     Copy.SearchModel.pickerHelp, Copy.SearchModel.sheetTitle] {
            for name in ["Google", "Gemma", "BAAI", "bge"] { XCTAssertFalse(text.contains(name), text) }
        }
    }
}

/// G182 phase 3 review — a bank built with the larger model on a Mac without it says so instead of claiming it searches.
final class SearchModelMissingTests: XCTestCase {
    func testABankBuiltWithAMissingModelSaysSearchUsesWords() {
        let status = EmbeddingsStatus(
            model: "google/embeddinggemma-300m",
            models: [EmbeddingModelOption(id: "BAAI/bge-small-en-v1.5", label: "Small", dimensions: 384, detail: "",
                                          needsDownload: false, available: true),
                     EmbeddingModelOption(id: "google/embeddinggemma-300m", label: "Larger", dimensions: 768, detail: "",
                                          needsDownload: true, available: false)])
        XCTAssertEqual(SearchModelLogic.detail(status), Copy.SearchModel.builtWithMissing("Larger"))
    }
}
