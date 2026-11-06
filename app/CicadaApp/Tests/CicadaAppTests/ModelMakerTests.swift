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
        // Meta's infinity is back in the set: a Llama, served by anyone, wears it.
        XCTAssertEqual(ContributorIdentity.modelMark(author: "ollama/llama3.2"), "meta-infinity")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "openrouter/meta-llama/llama-4-maverick"), "meta-infinity")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "together_ai/meta-llama/Llama-3.3-70B"), "meta-infinity")
    }

    func testAnUnknownMakerWearsTheRoutersMarkNotInitials() {
        // The router says who served it when the id does not say who made it (Rodrigo, 2026-11-06).
        XCTAssertEqual(ContributorIdentity.modelMark(author: "openrouter/some-lab/novel-7b"), "openrouter")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "openrouter/someone/qwen-finetune"), "openrouter")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "together_ai/some-lab/novel-7b"), "together")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "accounts/acme/models/deepseek-ft"), "fireworks")
        XCTAssertEqual(ContributorIdentity.modelMark(author: "ollama/novel-7b"), "ollama")
        // The maker still outranks the router, and an id with no router and no maker draws initials.
        XCTAssertEqual(ContributorIdentity.modelMark(author: "openrouter/z-ai/glm-5.2"), "zai")
        XCTAssertNil(ContributorIdentity.modelMark(author: "totally-new-model-1"))
        XCTAssertNil(ContributorIdentity.modelMark(author: "someone/qwen-finetune"))
    }

    func testEveryMakerMarkIsBundled() {
        for maker in ModelMaker.Maker.allCases {
            guard let name = ContributorIdentity.makerMark(maker) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(name).png is not bundled")
        }
        for router in ModelMaker.Router.allCases {
            guard let name = ContributorIdentity.routerMark(router) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(name).png is not bundled")
        }
    }
}
