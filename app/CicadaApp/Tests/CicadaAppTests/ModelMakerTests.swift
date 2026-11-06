import XCTest
@testable import CicadaApp

/// ROR-127 — a contributor wears the picture of the model's maker, whichever provider served it; an unknown maker
/// draws nothing (initials), never a guess.
final class ModelMakerTests: XCTestCase {

    func testARoutedIdIsReadByTheProvidersOwnOrganisationSegment() {
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/z-ai/glm-5.2"), .zai)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/anthropic/claude-opus-4"), .anthropic)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/deepseek/deepseek-chat-v3:free"), .deepseek)
        XCTAssertEqual(ModelMaker.maker(of: "together_ai/Qwen/Qwen3-235B-A22B"), .qwen)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/moonshotai/kimi-k2"), .moonshot)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/x-ai/grok-4"), .xai)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/minimax/minimax-m2"), .minimax)
    }

    func testAHostedModelUnderTheHostsOwnAccountIsReadByItsFamily() {
        XCTAssertEqual(ModelMaker.maker(of: "accounts/fireworks/models/deepseek-v3p1"), .deepseek)
        XCTAssertEqual(ModelMaker.maker(of: "fireworks_ai/accounts/fireworks/models/qwen3-235b-a22b"), .qwen)
        XCTAssertEqual(ModelMaker.maker(of: "accounts/fireworks/models/kimi-k2-instruct"), .moonshot)
    }

    func testABareIdIsReadByItsFamily() {
        XCTAssertEqual(ModelMaker.maker(of: "deepseek-chat"), .deepseek)
        XCTAssertEqual(ModelMaker.maker(of: "glm-5.2"), .zai)
        XCTAssertEqual(ModelMaker.maker(of: "claude-sonnet-4-5"), .anthropic)
        XCTAssertEqual(ModelMaker.maker(of: "gpt-5.4-mini"), .openai)
        XCTAssertEqual(ModelMaker.maker(of: "o3-mini"), .openai)
        XCTAssertEqual(ModelMaker.maker(of: "gemma-3-4b"), .google)
        XCTAssertEqual(ModelMaker.maker(of: "openrouter/glm-5.2"), .zai)
    }

    func testAnUnknownMakerIsNilNeverAGuess() {
        XCTAssertNil(ModelMaker.maker(of: "totally-new-model-1"))
        XCTAssertNil(ModelMaker.maker(of: "openrouter/some-lab/novel-7b"))
        XCTAssertNil(ModelMaker.maker(of: ""))
        // Somebody else's fine-tune is not the family's maker's work.
        XCTAssertNil(ModelMaker.maker(of: "someone/qwen-finetune"))
        XCTAssertNil(ModelMaker.maker(of: "accounts/acme/models/deepseek-ft"))
        // The o-series needs an anchored token, never a bare substring.
        XCTAssertNil(ModelMaker.maker(of: "macro1"))
        XCTAssertNil(ModelMaker.maker(of: "retro3-large"))
    }

    func testTheMarkFollowsTheMakerNotTheRouter() {
        XCTAssertEqual(ContributorIdentity.modelMark(author: "openrouter/z-ai/glm-5.2"), "zai")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "accounts/fireworks/models/deepseek-v3p1"), "deepseek")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "claude-sonnet-4-5"), "claude")
        // Unknown maker, or a maker with no bundled mark (Meta): initials, not the router's mark.
        XCTAssertNil(ContributorIdentity.modelMark(author: "openrouter/some-lab/novel-7b"))
        XCTAssertNil(ContributorIdentity.modelMark(author: "ollama/llama3.2"))
    }

    func testEveryMakerMarkIsBundled() {
        for maker in ModelMaker.Maker.allCases {
            guard let name = ContributorIdentity.makerMark(maker) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(name).png is not bundled")
        }
    }
}
