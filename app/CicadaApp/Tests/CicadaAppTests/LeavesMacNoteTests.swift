import XCTest
@testable import CicadaApp

/// R-AG14 (decision 5) — the note exists only where reads leave the Mac, names where they go, and never
/// mentions Ollama.
final class LeavesMacNoteTests: XCTestCase {
    private let providers = [
        SleepEngineProvider(id: "anthropic", label: "Anthropic", connectionId: "byok-anthropic", hasKey: true,
                            defaultModel: "anthropic/claude-haiku-4-5", keyUrl: "https://example.com"),
        SleepEngineProvider(id: "xai", label: "xAI", connectionId: "byok-xai", hasKey: false,
                            defaultModel: "xai/grok-4.5-latest", keyUrl: "https://example.com"),
    ]

    private func note(_ selected: String, provider: String? = nil, manual: String? = nil) -> String? {
        LeavesMacNote.text(selected: selected, provider: provider, manualEngine: manual, providers: providers)
    }

    func testOllamaAndAutoOnOllamaHaveNoNote() {
        XCTAssertNil(note("local"))
        XCTAssertNil(note("auto", manual: "ollama"))
    }

    func testEachEngineNamesWhereReadsGo() {
        XCTAssertEqual(note("agent"), "This is where information leaves your Mac. The Claude plan sends what it reads to Anthropic, under your plan's terms. Everything else stays here.")
        XCTAssertEqual(note("codex"), "This is where information leaves your Mac. The ChatGPT plan sends what it reads to OpenAI, under your plan's terms. Everything else stays here.")
        XCTAssertEqual(note("openrouter"), "This is where information leaves your Mac. OpenRouter sends what it reads to the model you picked, billed to your OpenRouter key. Everything else stays here.")
        XCTAssertEqual(note("byok", provider: "xai"), "This is where information leaves your Mac. Your xAI key sends what it reads to xAI. Everything else stays here.")
        // A `byok` model whose provider is not in the picker (an env-pinned id) still gets an honest note.
        XCTAssertEqual(note("byok"), "This is where information leaves your Mac. Your key sends what it reads to its provider. Everything else stays here.")
        XCTAssertEqual(note("auto", manual: "claude-cli"), note("agent"))
        XCTAssertEqual(note("auto", provider: "anthropic", manual: "litellm"), note("byok", provider: "anthropic"))
    }

    func testNoNoteEverSaysSlowerOrNamesOllama() {
        for selected in ["auto", "agent", "codex", "openrouter", "local", "byok"] {
            let text = note(selected, provider: "anthropic", manual: "claude-cli") ?? ""
            XCTAssertFalse(text.localizedCaseInsensitiveContains("slower"))
            XCTAssertFalse(text.localizedCaseInsensitiveContains("ollama"))
        }
        XCTAssertEqual(Copy.costModelLocal, "Free, on this Mac")
    }
}
