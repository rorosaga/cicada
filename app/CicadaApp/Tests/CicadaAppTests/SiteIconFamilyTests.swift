import XCTest
@testable import CicadaApp

/// The one fold from a site (a host, a URL, or a family's own key) to the family whose real mark ships in the app: a known
/// family never draws a monogram letter. The Swift site key is the host ("linkedin.com", `SourceSite.key`, a card's
/// `host`) while the bundled marks are keyed by family ("linkedin"); the backend's `mark_key` sends the family name.
final class SiteIconFamilyTests: XCTestCase {
    func testEveryHostFormFoldsToItsFamily() {
        let expected: [String: String] = [
            "x.com": "x", "twitter.com": "x", "www.x.com": "x", "mobile.twitter.com": "x", "x": "x", "twitter": "x",
            "youtube.com": "youtube", "m.youtube.com": "youtube", "youtu.be": "youtube", "youtube": "youtube",
            "linkedin.com": "linkedin", "www.linkedin.com": "linkedin", "lnkd.in": "linkedin", "linkedin": "linkedin",
            "instagram.com": "instagram", "github.com": "github", "gist.github.com": "github", "github": "github",
            "reddit.com": "reddit", "old.reddit.com": "reddit", "redd.it": "reddit", "tiktok.com": "tiktok",
            "https://www.linkedin.com/in/alpha": "linkedin", "X.COM": "x", "x.com:443": "x",
        ]
        for (site, family) in expected {
            XCTAssertEqual(SiteIconLayout.family(of: site), family, site)
        }
    }

    func testOtherSitesAndLookAlikesAreNoFamily() {
        for site in ["example.com", "paperfold.io", "box.com", "notx.com", "user.github.io", "linkedin.example.com", ""] {
            XCTAssertNil(SiteIconLayout.family(of: site), site)
        }
    }

    func testAHostDrawsTheBundledMarkNeverAMonogram() {
        for site in ["x.com", "twitter.com", "youtube.com", "linkedin.com", "instagram.com", "github.com", "reddit.com",
                     "tiktok.com"] {
            guard case .bundled(let name) = SiteIconLayout.rung(favicon: false, site: site, markExists: { _ in true }) else {
                return XCTFail("\(site) must draw a bundled mark")
            }
            XCTAssertEqual(name, SiteIconLayout.family(of: site), site)
        }
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "example.com", markExists: { _ in true }), .monogram)
        XCTAssertEqual(SiteIconLayout.rung(favicon: true, site: "linkedin.com"), .favicon, "the site's own icon still wins")
    }

    /// Every family mark the fold names is a file that ships, so the bundled rung is never an empty promise.
    func testEveryFamilyMarkShips() {
        for (family, file) in SiteIconLayout.familyMarks {
            XCTAssertTrue(LogoImage.exists(name: file), "\(family) -> \(file).png")
        }
    }

    /// The person page's "Sites and links" key is a host: it must reach the family's mark.
    func testThePersonPagesSiteKeyReachesTheMark() throws {
        let source = EntitySource(ref: "https://www.linkedin.com/in/alpha", kind: "url", addedBy: "person", addedAt: "2026-11-24")
        let key = try XCTUnwrap(SourceSite.key(of: source))
        XCTAssertEqual(key, "linkedin.com")
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: key, markExists: { _ in true }), .bundled("linkedin"))
    }
}
