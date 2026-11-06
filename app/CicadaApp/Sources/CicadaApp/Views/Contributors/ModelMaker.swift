import Foundation

/// Who MADE the model an author id names, whichever provider served it (ROR-127).
///
/// A contributor is drawn with the model's picture, not the picture of the service that billed for it:
/// `openrouter/z-ai/glm-5.2`, `accounts/fireworks/models/deepseek-v3p1` and a bare `deepseek-chat` are three routes to
/// two makers, and the picture follows the maker. Pure, view-free and tested; `ContributorIdentity.modelMark` is the
/// one place it is turned into a logo, so the avatar and the claim chip cannot disagree.
///
/// Two readings, in this order, and nothing else:
/// 1. **The provider's own data.** A routed id carries its maker as the organisation segment the provider publishes
///    (`z-ai/…`, `deepseek-ai/…`, `moonshotai/…`), so that segment is read first, through `orgs`.
/// 2. **The model's name**, only when the id carries no organisation at all (a bare `glm-5.2`, a hosted open model under
///    the host's own account) — the family markers in `families`.
///
/// **An organisation we do not know is a stranger, not a hint**: `someone/qwen-finetune` is not Qwen's, and a guess
/// would put a maker's mark on somebody else's work. It, and any id nothing names, answers nil — the contributor then
/// wears its initials, never a guess.
enum ModelMaker {

    /// The makers this reads, as the ids the logo map keys on.
    enum Maker: String, CaseIterable {
        case anthropic, openai, google, meta, mistral, deepseek, qwen, zai, moonshot, minimax, xai
    }

    /// Segments that name a route or a host, never a maker (the part of a LiteLLM / router id before the model).
    private static let routes: Set<String> = [
        "openrouter", "ollama", "litellm", "fireworks", "fireworks_ai", "fireworks-ai", "together", "together_ai",
        "togetherai", "deepinfra", "groq", "bedrock", "vertex_ai", "azure", "huggingface", "hf.co", "hf", "replicate",
        "accounts", "models", "routers", "api",
    ]

    /// An organisation segment → its maker, as each provider publishes it.
    private static let orgs: [String: Maker] = [
        "anthropic": .anthropic,
        "openai": .openai,
        "google": .google,
        "meta-llama": .meta, "meta": .meta, "facebook": .meta,
        "mistralai": .mistral, "mistral": .mistral,
        "deepseek-ai": .deepseek, "deepseek": .deepseek,
        "qwen": .qwen, "alibaba": .qwen,
        "z-ai": .zai, "zai-org": .zai, "zai": .zai, "thudm": .zai,
        "moonshotai": .moonshot, "moonshot": .moonshot,
        "minimax": .minimax, "minimaxai": .minimax,
        "x-ai": .xai, "xai": .xai,
    ]

    /// Family markers in a model's own name. Distinctive enough to be bare substrings, as the server's
    /// `git_service._PROVIDER_SUBSTRINGS` holds them; the o-series is anchored below.
    private static let families: [(Maker, [String])] = [
        (.openai, ["gpt", "text-embedding"]),
        (.anthropic, ["claude"]),
        (.google, ["gemini", "gemma"]),
        (.meta, ["llama"]),
        (.mistral, ["mistral", "mixtral", "codestral"]),
        (.deepseek, ["deepseek"]),
        (.qwen, ["qwen", "qwq"]),
        (.zai, ["glm"]),
        (.moonshot, ["kimi"]),
        (.minimax, ["minimax"]),
        (.xai, ["grok"]),
    ]

    /// The maker of the model an author id names, or nil when the id does not say.
    static func maker(of author: String) -> Maker? {
        let id = author.lowercased().trimmingCharacters(in: .whitespaces)
        guard !id.isEmpty else { return nil }
        let segments = id.split(separator: "/").map(String.init)
        guard let name = segments.last else { return nil }

        // The organisation is the segment just before the model's name, unless that segment is a route or a host.
        // `accounts/<account>/models/<name>` is a host's own layout: the account is the owner of the deployment, so it
        // is read like an organisation — and the host's own account (`fireworks`) names no maker, only the host.
        var org: String?
        if segments.count >= 2 {
            let before = segments[segments.count - 2]
            if before == "models", segments.count >= 4, segments[segments.count - 4] == "accounts" {
                org = segments[segments.count - 3]
            } else if !routes.contains(before) {
                org = before
            }
        }
        if let org, !routes.contains(org) {
            return orgs[org]   // known organisation → its maker; a stranger → nil, never a guess from the name
        }
        return family(of: name)
    }

    private static func family(of name: String) -> Maker? {
        for (maker, markers) in families where markers.contains(where: { name.contains($0) }) {
            return maker
        }
        // The o-series markers are too short for a bare substring ("macro1"): whole id, prefix, or delimited token.
        if name.range(of: #"(?:^|[-:])o[134](?:$|[-:])"#, options: .regularExpression) != nil { return .openai }
        return nil
    }
}
