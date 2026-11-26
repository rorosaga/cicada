import XCTest
@testable import CicadaApp

/// Ruling 84 (2026-11-26) — the folders Cicada's own agent may read: the list decodes, protected folders are one sentence and
/// never rows, a locked folder cannot be switched, a refusal puts the switch back with the backend's own sentence, and the app
/// sends only a path (it never reads the folder).
final class AgentReadFoldersTests: XCTestCase {
    static let json = """
    {"folders": [
      {"id": "Notes", "name": "Notes", "state": "default", "why": "", "granted": true, "locked": false, "added": false, "reason": "Notes and documents."},
      {"id": "vault", "name": "vault", "state": "default", "why": "notes_vault", "granted": true, "locked": false, "added": false, "reason": "Named for a vault, but it holds only notes, so it is on."},
      {"id": "secrets", "name": "secrets", "state": "refused", "why": "secrets", "granted": false, "locked": false, "added": false, "reason": "Its name says secrets, so it is off."},
      {"id": "oldbank", "name": "oldbank", "state": "refused", "why": "cicada", "granted": false, "locked": true, "added": false, "reason": "Cicada's own files. Never read."},
      {"id": "Documents", "name": "Documents", "state": "protected", "why": "protected", "granted": false, "locked": true, "added": false, "reason": "macOS keeps this folder closed."},
      {"id": "Desktop", "name": "Desktop", "state": "protected", "why": "protected", "granted": false, "locked": true, "added": false, "reason": "macOS keeps this folder closed."},
      {"id": "Library", "name": "Library", "state": "protected", "why": "system", "granted": false, "locked": true, "added": false, "reason": "The Mac's own folder, never read."},
      {"id": "Work/notes", "name": "Work/notes", "state": "on", "why": "", "granted": true, "locked": false, "added": true, "reason": "Turned on by you."}
    ]}
    """

    private func list() throws -> AgentReadFoldersResponse {
        try JSONDecoder().decode(AgentReadFoldersResponse.self, from: Data(Self.json.utf8))
    }

    func testTheListDecodesAndProtectedFoldersAreOneSentenceNeverRows() throws {
        let response = try list()
        XCTAssertEqual(response.folders.count, 8)
        XCTAssertEqual(response.shown.map(\.id), ["Notes", "vault", "secrets", "oldbank", "Work/notes"])
        XCTAssertEqual(response.protectedNames, ["Documents", "Desktop"], "the Mac's own Library is never named to the person")
        XCTAssertEqual(Copy.AgentReadFolders.protectedNote(response.protectedNames),
                       "macOS keeps Documents and Desktop closed to a read Cicada starts by itself, so they stay unread.")
        XCTAssertNil(Copy.AgentReadFolders.protectedNote([]))
    }

    func testASwitchMovesOnlyAFolderThatCanBeChanged() throws {
        let response = try list()
        let off = response.setting("vault", on: false)
        XCTAssertEqual(off.folders.first { $0.id == "vault" }?.state, "off")
        XCTAssertEqual(off.folders.first { $0.id == "vault" }?.granted, false)
        XCTAssertEqual(response.setting("oldbank", on: true), response, "a locked folder stays as it is")
        XCTAssertEqual(response.setting("nowhere", on: true), response)
    }

    @MainActor
    func testARefusalPutsTheSwitchBackWithTheBackendsSentence() async throws {
        let start = try list()
        var asked: [(String, Bool)] = []
        let model = AgentReadFoldersModel(deps: .init(
            load: { start },
            set: { id, on in
                asked.append((id, on))
                throw APIError.httpError(409, #"{"detail":"Cicada's own files. Never read."}"#)
            },
            add: { _ in start }, remove: { _ in start }))
        await model.load()
        await model.set("secrets", on: true)
        XCTAssertEqual(asked.map(\.0), ["secrets"])
        XCTAssertEqual(model.list, start)
        XCTAssertEqual(model.note, "Cicada's own files. Never read.")
        XCTAssertTrue(model.busy.isEmpty)
    }

    @MainActor
    func testAnAddedFolderSendsOnlyItsPathAndAShownRefusalLeavesTheListAlone() async throws {
        let start = try list()
        var paths: [String] = []
        let model = AgentReadFoldersModel(deps: .init(
            load: { start }, set: { _, _ in start },
            add: { path in
                paths.append(path)
                throw APIError.httpError(400, #"{"detail":"A hidden folder holds settings and keys, so it is never read."}"#)
            },
            remove: { _ in start }))
        await model.load()
        await model.add(path: "/Users/example/.hidden")
        XCTAssertEqual(paths, ["/Users/example/.hidden"])
        XCTAssertEqual(model.list, start)
        XCTAssertEqual(model.note, "A hidden folder holds settings and keys, so it is never read.")
    }

    @MainActor
    func testAFailedFirstLoadSaysSoAndALaterOneKeepsTheLastList() async throws {
        var fail = true
        let start = try list()
        let model = AgentReadFoldersModel(deps: .init(
            load: { if fail { throw APIError.serverUnreachable }; return start },
            set: { _, _ in start }, add: { _ in start }, remove: { _ in start }))
        await model.load()
        XCTAssertNil(model.list)
        XCTAssertTrue(model.loadFailed)
        fail = false
        await model.load()
        XCTAssertEqual(model.list, start)
        fail = true
        await model.load()
        XCTAssertEqual(model.list, start, "never blank once there was a list")
        XCTAssertFalse(model.loadFailed)
    }

    func testTheCopyNamesNoProvider() {
        let words = [Copy.AgentReadFolders.groupHeader, Copy.AgentReadFolders.lead, Copy.AgentReadFolders.addHelp,
                     Copy.AgentReadFolders.panelMessage, Copy.AgentReadFolders.switchLabel("vault")].joined(separator: " ").lowercased()
        for provider in ["claude", "anthropic", "openai", "gpt", "codex", "gemini", "ollama"] {
            XCTAssertFalse(words.contains(provider), provider)
        }
    }
}
