import Foundation

/// R-E27 — which bundled mark a connection wears, on Plans & keys and on the
/// Settings → Engines engine row. A key translation only: a connection id maps
/// to its vendor, and the file name comes from the one map that already owns
/// vendor marks (`ContributorIdentity.logoName(provider:)`), so this adds no
/// name a typo could break (CLAUDE.md, Brand marks: one map, one precedence).
/// The Claude plan wears Claude's mark and the ChatGPT plan ChatGPT's (spec
/// R-E4) — the card is named for the plan the person pays for, not for the
/// CLI Cicada drives. OpenRouter wears its own mark, fetched by a maintainer
/// from the vendor's repository at a pinned commit (R-AG9, origin `repo` in
/// `scripts/fetch-logos.sh` — never a runtime fetch). `nil` keeps the card's SF
/// Symbol: xAI, Groq and Mistral ship no sourced mark yet.
enum ConnectionMark {
    /// The vendor behind a connection, in `ContributorIdentity`'s provider ids.
    static func provider(connectionId: String) -> String? {
        switch connectionId {
        case "claude-plan", "byok-anthropic": "anthropic"
        case "chatgpt-plan", "byok-openai": "openai"
        case "byok-gemini": "google"
        case "ollama-local": "ollama"
        case "byok-openrouter": "openrouter"
        default: nil
        }
    }

    static func logoName(connectionId: String) -> String? {
        provider(connectionId: connectionId).flatMap { ContributorIdentity.logoName(provider: $0) }
    }

    static func symbol(isKeyBased: Bool) -> String { isKeyBased ? "key.fill" : "cpu" }
}
