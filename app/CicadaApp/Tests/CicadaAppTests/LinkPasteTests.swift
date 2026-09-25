import XCTest
@testable import CicadaApp

/// R-IB7 — a paste is a link only when it is one http(s) URL and nothing else.
final class LinkPasteTests: XCTestCase {
    func testOnlyASingleHTTPURLIsALink() {
        XCTAssertEqual(LinkPaste.url(in: "  https://example.com/a?b=1 \n")?.absoluteString, "https://example.com/a?b=1")
        XCTAssertNotNil(LinkPaste.url(in: "http://example.com"))
        XCTAssertNil(LinkPaste.url(in: "alpha-project"), "a search is not a link")
        XCTAssertNil(LinkPaste.url(in: "see https://example.com"), "words around a URL are a search")
        XCTAssertNil(LinkPaste.url(in: "file:///etc/hosts"))
        XCTAssertNil(LinkPaste.url(in: "javascript:alert(1)"))
        XCTAssertNil(LinkPaste.url(in: "https://"))
    }

    func testTheHostDropsALeadingWww() {
        XCTAssertEqual(LinkPaste.host(URL(string: "https://www.example.com/x")!), "example.com")
    }
}
