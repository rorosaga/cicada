import XCTest
@testable import CicadaApp

/// R-E28 — the in-app ChatGPT sign-in's decisions.
final class DeviceCodeLoginTests: XCTestCase {
    private func session(state: String = "pending", code: String? = "WXYZ-1234",
                         url: String? = "https://auth.openai.com/codex/device",
                         detail: String? = nil, rawOutput: String? = nil) throws -> LoginSession {
        var obj: [String: Any] = ["sessionId": "s1", "connectionId": "chatgpt-plan",
                                  "mode": "device-code", "state": state]
        if let code { obj["code"] = code }
        if let url { obj["url"] = url }
        if let detail { obj["detail"] = detail }
        if let rawOutput { obj["rawOutput"] = rawOutput }
        return try JSONDecoder().decode(LoginSession.self, from: JSONSerialization.data(withJSONObject: obj))
    }

    func testTheCodeShowsOnlyWithATrustedHttpsLink() throws {
        XCTAssertEqual(DeviceCodeLogin.phase(of: try session()),
                       .showCode(code: "WXYZ-1234", url: URL(string: "https://auth.openai.com/codex/device")!))
        for bad in ["http://auth.openai.com/device", "https://evil.example.com/openai.com",
                    "file:///etc/hosts", "https://openai.com.evil.example/"] {
            XCTAssertEqual(DeviceCodeLogin.phase(of: try session(url: bad)), .starting, bad)
        }
        XCTAssertEqual(DeviceCodeLogin.phase(of: try session(code: nil)), .starting)
    }

    func testTheLinkOpensOncePerSignIn() throws {
        let ready = try session()
        XCTAssertNotNil(DeviceCodeLogin.urlToOpen(ready, alreadyOpened: nil))
        XCTAssertNil(DeviceCodeLogin.urlToOpen(ready, alreadyOpened: "s1"))
        XCTAssertNil(DeviceCodeLogin.urlToOpen(try session(code: nil), alreadyOpened: nil))
    }

    func testAFailureAlwaysHasWordsAndDoneIsDone() throws {
        XCTAssertEqual(DeviceCodeLogin.phase(of: try session(state: "failed", code: nil, url: nil)),
                       .failed(Copy.deviceCodeFailed))
        XCTAssertEqual(DeviceCodeLogin.phase(of: try session(state: "failed", detail: "Sign-in didn't finish (codex exited 1).")),
                       .failed("Sign-in didn't finish (codex exited 1)."))
        XCTAssertEqual(DeviceCodeLogin.phase(of: try session(state: "done")), .done)
    }

    /// Final review H2: with no parsed code, what the sign-in printed is shown
    /// instead of a bare spinner — and never alongside a parsed code.
    func testThePrintedOutputIsTheFallbackOnlyWhileNoCodeParsed() throws {
        let printed = "Enter this one-time code\n   ABCD EFGH"
        XCTAssertEqual(DeviceCodeLogin.printedFallback(try session(code: nil, rawOutput: printed)),
                       "Enter this one-time code\n   ABCD EFGH")
        XCTAssertNil(DeviceCodeLogin.printedFallback(try session(code: nil, rawOutput: "  \n")))
        XCTAssertNil(DeviceCodeLogin.printedFallback(try session(rawOutput: printed)))
    }
}
