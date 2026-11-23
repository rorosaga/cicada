import Foundation

/// G104 slice 3 (T4, owner 2026-11-23): the run detail's "Corrections" section — what a run's corrections reached, said
/// in plain counts. Provider-neutral (no string names a model or a service as the one doing a job); a count is a count
/// of ids the server sent, never a title or a line of a conversation.
extension Copy {
    enum Corrections {
        static let title = "Corrections"
        static let restore = "Restore"
        static let restoring = "Restoring…"
        static let restored = "Restored"
        static let restoreFailed = "Could not restore it. Try again."
        static let restoreHelp = "Put this page back as it was before the correction"

        private static func n(_ count: Int, _ one: String, _ many: String, _ locale: Locale) -> String {
            "\(Copy.SleepV5.count(count, locale)) \(count == 1 ? one : many)"
        }

        /// "2 conversations were edited after they were read." — the lead line.
        static func revised(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            count == 1 ? "1 conversation was edited after it was read."
                       : "\(Copy.SleepV5.count(count, locale)) conversations were edited after they were read."
        }

        static func claimsWithdrawn(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "claim", "claims", locale)) only the removed words supported \(count == 1 ? "was" : "were") withdrawn"
        }

        static func claimsSuperseded(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "claim", "claims", locale)) replaced by what the edit now says"
        }

        static func passagesRewritten(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "passage", "passages", locale)) rewritten"
        }

        static func aliasesDropped(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "alias", "aliases", locale)) dropped"
        }

        static func heldDropped(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "claim", "claims", locale)) held for a name not yet on a page dropped"
        }

        static func questionsWithdrawn(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "question", "questions", locale)) withdrawn"
        }

        static func pagesArchived(_ count: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(n(count, "page", "pages", locale)) archived, because only the edited words supported \(count == 1 ? "it" : "them")"
        }

        /// "3 pages kept because something else supports them (another conversation, a source you added)".
        static func pagesKept(_ count: Int, supports: [String], _ locale: Locale = .autoupdatingCurrent) -> String {
            let head = "\(n(count, "page", "pages", locale)) kept because something else supports \(count == 1 ? "it" : "them")"
            return supports.isEmpty ? head : "\(head) (\(supports.joined(separator: ", ")))"
        }

        /// The server's support enum (`revision_cascade.SUPPORTS`) in the person's words; `nil` for one this build has no
        /// word for — never a guess, never the raw enum.
        static func supportWords(_ support: String) -> String? {
            switch support {
            case "owner": "your own page"
            case "project": "a project you started"
            case "media": "a saved item"
            case "pinned": "an edit you made"
            case "contacts": "a Contacts card"
            case "person_source": "a source you added"
            case "import": "an import"
            case "other_conversation": "another conversation"
            case "surviving_claim": "a claim that still stands"
            case "authored_commit": "a change you or an agent made"
            case "waiting_conversation": "a conversation still waiting to be read"
            default: nil
            }
        }
    }
}

/// The section's lines, pure so `CorrectionsSectionTests` holds them: a count of zero says nothing.
enum CorrectionsPresentation {
    static func lines(_ c: SleepRunDetail.Corrections, locale: Locale = .autoupdatingCurrent) -> [String] {
        var out: [String] = []
        if c.conversationsRevised > 0 { out.append(Copy.Corrections.revised(c.conversationsRevised, locale)) }
        if c.claimsWithdrawn > 0 { out.append(Copy.Corrections.claimsWithdrawn(c.claimsWithdrawn, locale)) }
        if c.claimsSuperseded > 0 { out.append(Copy.Corrections.claimsSuperseded(c.claimsSuperseded, locale)) }
        if c.passagesRewritten > 0 { out.append(Copy.Corrections.passagesRewritten(c.passagesRewritten, locale)) }
        if c.aliasesDropped > 0 { out.append(Copy.Corrections.aliasesDropped(c.aliasesDropped, locale)) }
        if c.heldDropped > 0 { out.append(Copy.Corrections.heldDropped(c.heldDropped, locale)) }
        if c.questionsWithdrawn > 0 { out.append(Copy.Corrections.questionsWithdrawn(c.questionsWithdrawn, locale)) }
        return out
    }

    /// The kept pages' one line, with each distinct reason once, in the order the server listed them.
    static func keptLine(_ c: SleepRunDetail.Corrections, locale: Locale = .autoupdatingCurrent) -> String? {
        guard !c.pagesKept.isEmpty else { return nil }
        var seen: [String] = []
        for kept in c.pagesKept {
            if let words = Copy.Corrections.supportWords(kept.support), !seen.contains(words) { seen.append(words) }
        }
        return Copy.Corrections.pagesKept(c.pagesKept.count, supports: seen, locale)
    }

    static func archivedLine(_ c: SleepRunDetail.Corrections, locale: Locale = .autoupdatingCurrent) -> String? {
        c.pagesArchived.isEmpty ? nil : Copy.Corrections.pagesArchived(c.pagesArchived.count, locale)
    }
}
