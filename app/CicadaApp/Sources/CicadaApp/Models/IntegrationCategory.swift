import Foundation

/// Settings → Integrations (G126) groups every `GET /sources/channels` row
/// into one of six sections — a different cut than the Sources grid's
/// `SourceKind` (which groups by *what the backend counts*, harness vs.
/// browser vs. social), because Integrations is about *where you go to
/// manage a connection*, not what it contributes to the graph. Chat exports
/// and MCP-captured harnesses share a section here (both are "how an agent
/// conversation gets in") even though `SourceKind` keeps `.harness` and
/// `.import` apart.
///
/// `of(channelId:)` mirrors `api/services/channel_registry.py::CHANNEL_IDS`
/// (13 ids, verified against `dev` @ `2312887`) — a future 14th id needs
/// this switch AND `IntegrationsViewTests.testEveryChannelIdHasACategory`
/// updated together. The `default` case is unreachable given that list, but
/// returns `.filesAndImports` rather than crashing: an unrecognised id from
/// a newer backend degrades to "somewhere on the page" instead of taking
/// the app down.
enum IntegrationCategory: String, CaseIterable, Identifiable {
    case chatAndAgents, browsers, socialAndSaved, feedsAndCalendars, messaging, filesAndImports

    var id: String { rawValue }

    /// Plain literals, not `Copy.*` — these are page-local section headers
    /// with no cross-page pointer to drift from, unlike `SettingsSection`'s
    /// titles (R7 is about pointers to OTHER pages, not every string in the
    /// app).
    var title: String {
        switch self {
        case .chatAndAgents: "Chat & agents"
        case .browsers: "Browsers"
        case .socialAndSaved: "Social & saved"
        case .feedsAndCalendars: "Feeds & calendars"
        case .messaging: "Messaging"
        case .filesAndImports: "Files & imports"
        }
    }

    static func of(channelId: String) -> IntegrationCategory {
        switch channelId {
        case "chat-export:claude", "chat-export:chatgpt":
            return .chatAndAgents
        case "chrome-bookmarks", "safari-bookmarks", "safari-tabs":
            return .browsers
        case "pinterest", "reddit", "x":
            return .socialAndSaved
        case "rss", "calendar":
            return .feedsAndCalendars
        case "telegram":
            return .messaging
        case "notes", "files":
            return .filesAndImports
        default:
            return .filesAndImports
        }
    }
}

/// The "captured by the Stop hook / MCP" informational rows this page adds
/// under Chat & agents — exactly the `kind == .harness` rows the Sources
/// grid already carries in `Store.sourcesOverview` (G124), so a harness like
/// Claude Code or Cursor shows up here with no second fetch and no new
/// backend field.
enum IntegrationHarnessRows {
    static func rows(from overview: [SourceOverview]) -> [SourceOverview] {
        // A row that HAS a channel id is already rendered by this page as a
        // real, connectable channel — `api/services/source_overview.py:50`
        // gives `chat-export:*` both `kind = "harness"` and a `channel`, so
        // taking `kind` alone printed every chat export twice, the second copy
        // captioned "Captured automatically — no setup needed" (false: an
        // export is a one-shot file drop). The informational rows this list is
        // for are the ones with nothing to connect: Claude Code, Cursor, Codex.
        overview.filter { $0.kind == .harness && $0.channelId == nil }
    }
}

/// R8 — the state line is a dedicated pure formatter, not `SourceChannel.
/// detail`. The backend's `detail` differs in shape per channel kind
/// (bookmarks say "X bookmarks · synced …", a connector says "+N this sync
/// · synced …", a feed says "N feeds · polled …") — fine for the existing
/// Sources grid, but Integrations groups all of them in one visual
/// language, so this composes connected-state, a relative last-sync time,
/// the count and the error into one consistent sentence instead of six.
enum IntegrationRowState {
    /// R-S5 — `locale:` is a parameter, defaulted, for the same reason
    /// `UsageFormat.count` takes one: this line and the Sources grid render the
    /// same channel's count one tab apart, and a test has to be able to assert
    /// that they group identically without asserting the tester's own Mac.
    static func line(_ channel: SourceChannel, now: Date = Date(),
                     locale: Locale = .autoupdatingCurrent) -> String {
        guard channel.connected else { return "Not connected" }

        var parts: [String] = []
        if let date = channel.lastSyncDate {
            let fmt = RelativeDateTimeFormatter()
            fmt.unitsStyle = .abbreviated
            parts.append(fmt.localizedString(for: date, relativeTo: now))
        }
        if channel.count > 0 {
            // R-S5 — this was a bare `\(channel.count)`, which in a
            // `LocalizedStringKey` grouped in the viewer's locale and in a
            // plain `String` did not group at all. It is a `parts.append`, not
            // a `Text("`, so `CountLiteralLintTests`' needle cannot see it —
            // `SourcesV2Tests.testTheIntegrationsRowCountsInTheSameFormatterAsTheGrid`
            // is what holds it instead.
            let n = UsageFormat.count(channel.count, locale: locale)
            parts.append("\(n) item\(channel.count == 1 ? "" : "s")")
        }
        var line = parts.isEmpty ? "Connected" : parts.joined(separator: " · ")
        if let error = channel.lastError {
            line += " · \(error)"
        }
        return line
    }
}
