import Foundation

/// Sources v4 (owner 2026-10-19) — the words of a source's one header, its faces and its watched days.
extension Copy {
    static let consolidateSourceHelp = "Read what is waiting now — Sleep reads everything waiting, this source included"

    /// "+4" in the circle after a row's faces; spoken in full.
    static func facesMore(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "+\(UsageFormat.count(n, locale: locale))"
    }
    static func facesSpoken(_ labels: [String], more: Int) -> String {
        let named = labels.joined(separator: ", ")
        return more > 0 ? "\(named) and \(more) more" : named
    }

    /// A watched day's row: "12 videos" (DR-21: the unit is always said).
    static func watchedVideos(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "video" : "videos")"
    }
    static let watchedDayLoading = "Reading that day…"
    static let watchedDayFailed = "Couldn't read that day. Try opening it again."
    static let watchedDayEmpty = "No videos recorded for that day."
    static let watchedOpenHelp = "Open the video"
    static let watchedOpenSavedHelp = "Open in Saved — you saved this one too"
    static func watchedTimes(_ n: Int) -> String { n > 1 ? "watched \(n) times" : "" }

    /// A Messages chat's row (review of #358): "3 sittings"; a sitting under it: "12 messages".
    static func chatSittings(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "sitting" : "sittings")"
    }
    static func chatMessages(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "message" : "messages")"
    }
    static let chatSittingUndated = "Undated"
    static let chatSittingsLoading = "Reading this chat…"
    static let chatSittingsFailed = "Couldn't read this chat. Try opening it again."

    /// Conversations' find (DR-46): the list header's magnifier opens it.
    static let conversationsTitle = "Conversations"
    static let conversationsFind = "Find a conversation by title"

    /// A conversation row's count (ruling 39, 2026-10-24): the row is one conversation, and the number is how many
    /// times it was saved — its capture plus what the agent saved in it — never "episodes" (DR-59).
    static func conversationSaved(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "Saved once" : "Saved \(UsageFormat.count(n, locale: locale)) times"
    }
    /// The pages a conversation wrote, counted where the row does not list them by name.
    static func conversationPages(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "page" : "pages")"
    }
}
