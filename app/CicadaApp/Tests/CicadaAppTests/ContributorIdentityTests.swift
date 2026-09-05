import XCTest
@testable import CicadaApp

/// R-L6/R8 — who wrote your memory, rendered honestly: Cicada's own
/// maintenance is labelled as such, a model with a bundled mark wears it, and
/// anything unmatched gets initials rather than the grey "?" that made four
/// distinct authors look like one anonymous row.
final class ContributorIdentityTests: XCTestCase {

    func testTheSystemAuthorIsNamedNotLeftAsAnId() {
        XCTAssertEqual(ContributorIdentity.displayName(author: "cicada", kind: "system"),
                       "Cicada · maintenance")
        // R-S13 — this pinned the RAW id "user" only because Track L had no
        // reason to change it. The strip made it a defect: a bank the person
        // wrote themselves listed a contributor called "user" (critique E1).
        XCTAssertEqual(ContributorIdentity.displayName(author: "user", kind: "user"), Copy.you)
        XCTAssertEqual(ContributorIdentity.displayName(author: "gpt-5.4-mini", kind: "model"),
                       "gpt-5.4-mini")
    }

    func testProvidersWithABundledMarkUseIt() {
        XCTAssertEqual(ContributorIdentity.logoName(provider: "anthropic"), "claude")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "openai"), "chatgpt")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "google"), "gemini")
        XCTAssertEqual(ContributorIdentity.logoName(provider: "ollama"), "ollama")
        XCTAssertNil(ContributorIdentity.logoName(provider: "openrouter"))
        XCTAssertNil(ContributorIdentity.logoName(provider: nil))
        for name in ContributorIdentity.allProviderMarks {
            XCTAssertTrue(LogoImage.exists(name: name), "\(name).png is not bundled")
        }
    }

    func testAnUnmatchedModelGetsInitialsNeverAQuestionMark() {
        XCTAssertEqual(ContributorIdentity.monogram(for: "openrouter/z-ai/glm-5.2"), "OZ")
        XCTAssertEqual(ContributorIdentity.monogram(for: "glm-5.2"), "G5")
        XCTAssertNotEqual(ContributorIdentity.monogram(for: "glm-5.2"), "?")
    }
}
