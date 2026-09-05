import Foundation

/// How a `Cicada-Author` is *named and marked* in the contributors list —
/// pure, view-free and tested, so the three places a contributor is rendered
/// (the row name, the avatar, the accessibility label) cannot disagree.
///
/// Track L R8/R-L6. Before this, `ContributorAvatar` mapped a provider to one
/// of three letters and everything else to a grey circle with a white "?" —
/// so `cicada` (the state snapshot, the split-out decay commit, the one-shot
/// migrations), an OpenRouter id and a local Llama all rendered as the same
/// anonymous unknown. Two rules replace it:
///
/// 1. **A provider with a bundled mark wears the real mark** — the same PNGs
///    every other surface uses, resolved through `LogoImage`.
/// 2. **Anything unmatched gets initials, never "?"** — two authors that
///    differ are two badges that differ.
enum ContributorIdentity {

    /// The literal author of system maintenance: no model, no user in the
    /// loop. Mirrors `git_service.CICADA_AUTHOR`, and is what the `kind`
    /// fallback keys on when an older backend ships no `kind` at all.
    static let systemAuthor = "cicada"

    /// What the row calls this contributor. Every author but the system one is
    /// its own id: a model id is the honest name of the thing that wrote, and
    /// prettifying it would hide which build actually ran.
    static func displayName(author: String, kind: String?) -> String {
        kind == "system" || author == systemAuthor ? "Cicada · maintenance" : author
    }

    /// The bundled logo for a provider, or nil when the provider has no mark
    /// we ship (a router — `openrouter` bills but has no committed mark — or
    /// an open-weight family whose glyph is not in `Resources/logos`). nil
    /// means "fall back to the coloured circle with initials", never a blank.
    ///
    /// Deliberately a provider→file map and not an identity: the provider ids
    /// come from `git_service._PROVIDER_SUBSTRINGS` and the file names come
    /// from the products (`anthropic` ships as `claude`, `openai` as
    /// `chatgpt`, `google` as `gemini`).
    static func logoName(provider: String?) -> String? {
        switch provider {
        case "anthropic": "claude"
        case "openai": "chatgpt"
        case "google": "gemini"
        case "ollama": "ollama"
        default: nil
        }
    }

    /// Every mark this map can return. An array rather than a Set because
    /// `LogoAssetTests.testEveryBundledMarkIsClaimedBySomeMap` concatenates it
    /// into the claimed-names list — this is the only thing that stops a
    /// provider mark from reading as an orphaned asset.
    static let allProviderMarks: [String] = ["claude", "chatgpt", "gemini", "ollama"]

    /// Initials for the badge when no mark applies. Delegates to
    /// `LogoImage.monogram(for:)` so a contributor badge and a platform tile
    /// derive initials by exactly one rule — and it is fed the AUTHOR, not the
    /// provider, because the author is what actually distinguishes two rows.
    static func monogram(for author: String) -> String {
        LogoImage.monogram(for: author)
    }
}
