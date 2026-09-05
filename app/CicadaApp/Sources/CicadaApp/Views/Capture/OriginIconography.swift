import SwiftUI

/// The single source of truth for "how does this origin id read as a label
/// / SF Symbol / brand color" — extracted out of `OriginPill` (G106
/// amendment) so the Sleep debt breakdown's per-source grouping can reuse
/// the exact same iconography instead of re-declaring its own switch
/// statements that would inevitably drift from this one.
///
/// `label(for:)`'s cases for every id `OriginPill` already handled before
/// this extraction are byte-for-byte what it returned — including
/// `reddit-saved` ("Reddit Saved") and `x-bookmarks` ("X Bookmarks"), both
/// deliberate, already-reviewed choices (the G71 final-review M2 fix that
/// first added them) an earlier pass of this extraction briefly shortened
/// to "Reddit"/"X" by mistake; restored here (review M3). The bare
/// `"reddit"`/`"x"` cases are NEW, defensive aliases this extraction added
/// — no real episode ever carries them (connector-authored episodes use
/// the `-saved`/`-bookmarks` forms) — and get their own, intentionally
/// shorter labels since they aren't standing in for an existing behavior.
enum OriginIconography {
    /// Every origin id a writer stamps today, plus the defensive aliases. The
    /// bundle test drives off this list, so the list and the switches cannot
    /// drift — adding a case without adding it here is the bug (T1,
    /// `OriginIconographyTests.testEveryDeclaredLogoExistsInTheBundle`), and
    /// `LogoAssetTests`' T2 sweeps the same list in the other direction to
    /// catch a bundled PNG nothing claims.
    ///
    /// Verified against the backend by
    /// `grep -rhoE '"origin": *"[a-z0-9:_-]+"|origin *= *"[a-z0-9:_-]+"' api mcp --include='*.py'`
    /// (quote the `--include`; zsh globs it otherwise) and against
    /// `api/services/source_overview.py::CATALOG`'s `mark`/`origins` columns.
    static let allKnownOrigins: [String] = [
        "mcp", "claude-code", "claude-desktop", "cursor", "codex", "gemini-cli",
        "claude-export", "chatgpt-export", "gemini-export",
        "chrome-bookmark", "safari-bookmark", "safari-tab", "apple-notes",
        "telegram", "rss", "calendar", "share-sheet", "bookmark", "saved-link",
        "instagram-saved", "youtube-playlist", "pinterest", "reddit-saved", "reddit",
        "x-bookmarks", "x", "linkedin-saved", "tiktok-saved", "tiktok-history", "unknown",
    ]

    static func label(for origin: String) -> String {
        switch origin {
        // "mcp" is the legacy label, kept byte-for-byte so any existing
        // caller (the Sleep debt breakdown; the Sources grid since G124)
        // never silently renames — "claude-code" is the newer G9-normalized
        // id for the same source and gets its own, equally legible label.
        case "mcp": "MCP"
        case "claude-code": "Claude Code"
        // G124 R17 — harness ids an MCP client stamps (`mcp/server.py`
        // SESSION) read as the Sources grid's harness cards. Generic on
        // purpose: an unlisted harness falls through to `capitalized`.
        case "cursor": "Cursor"
        case "codex": "Codex"
        case "claude-desktop": "Claude Desktop"
        case "chrome-bookmark": "Chrome"
        case "safari-bookmark": "Safari"
        // R3 — iCloud tabs are their own origin so a tab and a bookmark from
        // the same browser stay distinguishable in the origins strip.
        case "safari-tab": "Safari tab"
        case "telegram": "Telegram"
        case "claude-export": "Claude export"
        case "chatgpt-export": "ChatGPT export"
        // The Gemini Takeout importer's origin (`conversations.py`). The
        // backend has shipped a Sources card for it since G124 while the app
        // had no case, so the card read "Gemini-export" under a generic tray.
        case "gemini-export": "Gemini export"
        case "rss": "RSS"
        case "calendar": "Calendar"
        case "apple-notes": "Apple Notes"
        case "share-sheet": "Share Sheet"
        case "instagram-saved": "Instagram Saved"
        case "youtube-playlist": "YouTube Playlist"
        case "pinterest": "Pinterest"
        case "reddit-saved": "Reddit Saved"
        case "x-bookmarks": "X Bookmarks"
        case "linkedin-saved": "LinkedIn Saved"
        case "tiktok-saved": "TikTok Saved"
        case "tiktok-history": "TikTok History"
        case "bookmark": "Bookmark"
        // The `files` row's own origin (`source_overview.CATALOG`): what
        // `POST /sources/save` and `cicada_save_url`'s backend-down path
        // stamp. It had no case at all, so it read as "Saved-link" — a
        // `.capitalized` id, visibly not a product name.
        case "saved-link": "Saved link"
        // G105: hook-driven harness capture. Product names, not ids — the
        // Sleep queue's "Catching up on" block reads these aloud. `codex`,
        // `claude-desktop` and `cursor` belong to this group too and are
        // spelled once, above: a second copy here was unreachable (Swift takes
        // the first match) and told the next editor a lie about where to edit.
        case "gemini-cli": "Gemini CLI"
        case "unknown": "Unknown"
        // Defensive aliases only — see the type doc above.
        case "reddit": "Reddit"
        case "x": "X"
        default: origin.capitalized
        }
    }

    static func symbol(for origin: String) -> String {
        switch origin {
        case "mcp", "claude-code", "cursor", "codex", "claude-desktop": "bubble.left.and.bubble.right"
        case "chrome-bookmark": "globe"
        case "safari-bookmark", "safari-tab": "safari"
        case "telegram": "paperplane.fill"
        case "claude-export", "chatgpt-export", "gemini-export": "square.and.arrow.down"
        case "rss": "dot.radiowaves.up.forward"
        case "calendar": "calendar"
        case "apple-notes": "note.text"
        case "share-sheet": "square.and.arrow.up"
        case "instagram-saved": "camera.fill"
        case "youtube-playlist": "play.rectangle.fill"
        case "pinterest": "pin.fill"
        case "reddit-saved", "reddit": "bubble.left.and.text.bubble.right.fill"
        case "x-bookmarks", "x": "x.circle"
        case "linkedin-saved": "briefcase.fill"
        case "tiktok-saved": "music.note"
        case "tiktok-history": "clock.arrow.circlepath"
        case "bookmark": "bookmark.fill"
        case "saved-link": "link"
        // `gemini-cli` ALONE: `codex`, `cursor` and `claude-desktop` are
        // already matched by the first case above, so this case never answered
        // `terminal` for them. `gemini-cli` is the one id here that is not
        // shadowed, and `terminal` is its live answer — narrowing the case,
        // not deleting it, is what keeps that true.
        case "gemini-cli": "terminal"
        case "unknown": "questionmark.circle"
        default: "tray"
        }
    }

    static func color(for origin: String) -> Color {
        switch origin {
        case "mcp", "claude-code", "claude-desktop": CicadaTheme.accent
        case "cursor": Color(hex: 0x6E56CF)
        case "codex": Color(hex: 0x10A37F)
        case "chrome-bookmark": Color(hex: 0x4285F4)
        case "safari-bookmark", "safari-tab": Color(hex: 0x00A2E8)
        case "telegram": Color(hex: 0x26A5E4)
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        case "apple-notes": Color(hex: 0xFFCC00)
        case "share-sheet": Color(hex: 0x8896FF)
        case "instagram-saved": Color(hex: 0xE1306C)
        case "youtube-playlist": Color(hex: 0xFF0000)
        case "pinterest": Color(hex: 0xE60023)
        case "reddit-saved", "reddit": Color(hex: 0xFF4500)
        case "x-bookmarks", "x": Color(hex: 0x14171A)
        case "linkedin-saved": Color(hex: 0x0A66C2)
        case "tiktok-saved", "tiktok-history": Color(hex: 0xFE2C55)
        // Google blue, the same swatch the Chrome row carries — same vendor,
        // and this tint is only ever seen when the bundled mark is missing.
        case "gemini-export": Color(hex: 0x4285F4)
        // Matches `ConnectedChannelRow.tint(for: "files")`: `saved-link` is
        // that row's origin, and R-L4's whole point is that one source is one
        // picture wherever it is drawn.
        case "saved-link": Color(hex: 0x8896FF)
        // `gemini-cli` alone — see the same narrowing in `symbol` above.
        case "gemini-cli": CicadaTheme.textPrimary
        case "unknown": CicadaTheme.textTertiary
        default: CicadaTheme.textSecondary
        }
    }

    /// The bundled PNG under `Resources/logos/` for an origin — the ONE id →
    /// asset map (R-L4). `ConnectedChannelRow.logoName` delegates here through
    /// `origin(forChannel:)`, and `source_overview.SourceSpec.mark` is already
    /// an origin id, so the Sleep desk, the Sources grid, the `+` catalog and
    /// Settings → Integrations cannot disagree about what a source looks like.
    ///
    /// `mcp` shares Claude Code's mark: it is the same harness under its
    /// legacy id. Safari and Apple Notes are deliberately absent — R-L3
    /// forbids redistributing Apple's marks, so they resolve through
    /// `appBundleId` and then their own SF Symbol. Calendar is absent for a
    /// different reason (R3): the only freely-licensed calendar mark is
    /// *Google* Calendar and this origin is any ICS publisher.
    ///
    /// Exhaustive by test over `allKnownOrigins`
    /// (`OriginIconographyTests.testEveryDeclaredLogoExistsInTheBundle`), so a
    /// typo fails before it ships a blank mark.
    static func logoName(for origin: String) -> String? {
        switch origin {
        case "claude-code", "mcp": "claude-code"
        case "codex": "codex"
        case "claude-export", "claude-desktop": "claude-desktop"
        case "cursor": "cursor"
        case "gemini-cli": "gemini-cli"
        case "chatgpt-export": "chatgpt"
        case "gemini-export": "gemini"
        case "chrome-bookmark": "chrome"
        case "rss": "rss"
        case "telegram": "telegram"
        case "pinterest": "pinterest"
        case "reddit-saved", "reddit": "reddit"
        case "x-bookmarks", "x": "x"
        case "linkedin-saved": "linkedin"
        case "tiktok-saved", "tiktok-history": "tiktok"
        case "instagram-saved": "instagram"
        case "youtube-playlist": "youtube"
        default: nil
        }
    }

    /// The app installed on THIS Mac whose icon is this origin's mark (R-L1),
    /// or nil when the origin is not a local app Cicada reads files from.
    ///
    /// Sound by construction: Cicada only offers a Chrome / Safari / Apple
    /// Notes channel because it reads that app's own files off this Mac, so
    /// the app is present and its icon is already on disk. This rung sits in
    /// FRONT of the bundled PNG in `OriginMark` and `PlatformTile` — it can
    /// never go stale when a vendor rebrands, and it is the only mark Safari
    /// and Apple Notes will ever have (R2/R-L3 forbid committing Apple's).
    /// The drawn glyphs this replaced were wrong on four axes for Chrome and
    /// an invented tint for Safari.
    static func appBundleId(for origin: String) -> String? {
        switch origin {
        case "safari-bookmark", "safari-tab": "com.apple.Safari"
        case "chrome-bookmark": "com.google.Chrome"
        case "apple-notes": "com.apple.Notes"
        default: nil
        }
    }
}
