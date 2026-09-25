import XCTest
@testable import CicadaApp

/// R-AG10 — the OpenRouter card keeps its key field and gains a sign-in; the app opens only OpenRouter's own
/// https URL off the wire.
final class ConnectionOAuthTests: XCTestCase {
    private func session(_ url: String?, mode: String = "oauth", id: String = "byok-openrouter") throws -> LoginSession {
        let json = """
        {"sessionId":"s","connectionId":"\(id)","mode":"\(mode)","state":"pending"\(url.map { ",\"url\":\"\($0)\"" } ?? "")}
        """
        return try JSONDecoder().decode(LoginSession.self, from: Data(json.utf8))
    }

    func testOnlyOpenRoutersOwnHttpsURLOpens() throws {
        XCTAssertNotNil(ConnectionLogin.browserURL(for: try session("https://openrouter.ai/auth?x=1")))
        XCTAssertNil(ConnectionLogin.browserURL(for: try session("http://openrouter.ai/auth")))
        XCTAssertNil(ConnectionLogin.browserURL(for: try session("https://openrouter.ai.example.com/auth")))
        XCTAssertNil(ConnectionLogin.browserURL(for: try session("https://openrouter.ai/auth", id: "byok-openai")))
        XCTAssertNil(ConnectionLogin.browserURL(for: try session("https://openrouter.ai/auth", mode: "key")))
        XCTAssertNil(ConnectionLogin.browserURL(for: try session(nil)))
    }

    func testAnOAuthCardIsStillAKeyCard() throws {
        let card = try JSONDecoder().decode(ConnectionStatus.self, from: Data(
            #"{"id":"byok-openrouter","label":"OpenRouter API key","kind":"usage","login":{"mode":"oauth"}}"#.utf8))
        XCTAssertTrue(card.isKeyBased, "the paste field stays")
        XCTAssertTrue(card.signsIn)
        let plain = try JSONDecoder().decode(ConnectionStatus.self, from: Data(
            #"{"id":"byok-groq","login":{"mode":"key"}}"#.utf8))
        XCTAssertTrue(plain.isKeyBased)
        XCTAssertFalse(plain.signsIn)
        XCTAssertEqual(Copy.signInWithOpenRouter, "Sign in with OpenRouter")
    }
}
