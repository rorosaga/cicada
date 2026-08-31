import Foundation

/// Every string that points the reader at another part of the app, plus the
/// page subtitles and the shared action verbs (G68 §2.8).
///
/// Two rules, enforced by `CopyConstantsTests`:
///  1. A cross-page pointer names its destination exactly as the sidebar or
///     the Settings tab spells it, so what the user reads is what they can
///     look for.
///  2. A page subtitle is one sentence, ≤ 60 characters, never a repeat of
///     the title above it, and never says "page".
enum Copy {

    // MARK: Destinations

    static let settings = "Settings"
    static let plansAndKeys = "Plans & keys"
    static let agents = "Agents"
    static let feed = "Feed"
    static let activity = "Activity"

    /// The canonical way to send someone to the connections settings. Built
    /// from the parts above so a rename can never desync the two halves.
    static let settingsPlansAndKeys = "\(settings) → \(plansAndKeys)"

    // MARK: Shared action verbs
    //
    // One verb per action, app-wide. The Sleep page used to say "Run now" /
    // "Running…" while the queue card said "Consolidate now" / "Sleeping…"
    // for the identical POST.

    static let consolidateNow = "Consolidate now"
    static let consolidating = "Consolidating…"

    // MARK: Observer

    /// The user's own observer label. Never the account holder's first name —
    /// the app is single-user, and "You" reads correctly for anyone.
    static let you = "You"

    // MARK: Page subtitles

    static let clustersSubtitle = "Every entity, grouped by type."
    static let feedSubtitle = "Everything Cicada has read, newest first."
    static let sleepSubtitle = "Fold today's episodes into the graph."
    static let inboxSubtitle = "Questions waiting on you."
    static let agentsSubtitle = "Wire any MCP agent into this Mac's memory."
    static let plansAndKeysSubtitle = "What Cicada bills against, and how it signs in."
    static let activitySubtitle = "What Cicada spent, and who authored what."

    // MARK: Pointers

    static let noConnections = "No connections yet — add one in \(settingsPlansAndKeys)."

    /// Section label above the origins strip. Sentence-shaped on purpose —
    /// it explains a row of pills that would otherwise read as decoration.
    static let originsLabel = "WHERE YOUR MEMORY COMES FROM"

    // MARK: Derived

    /// The Clusters list count. It counts entities and the type groups they
    /// fall into — the page never detected a "cluster" and must not say it did.
    static func clusterCount(entities: Int, groups: Int) -> String {
        "\(entities) \(entities == 1 ? "entity" : "entities") in \(groups) \(groups == 1 ? "group" : "groups")"
    }
}
