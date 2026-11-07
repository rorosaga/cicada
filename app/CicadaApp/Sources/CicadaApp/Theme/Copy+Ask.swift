import Foundation

/// Ask's answer: the words beside the page sources (2026-10-19). Provider-neutral — the step, never who did it.
extension Copy {
    enum AskWords {
        /// The section under an answer listing the conversations it used that no page cites (Ask's search leg).
        static let fromConversations = "From conversations"
        /// What the section means, for `.help` and VoiceOver: these are not pages, they are what was said.
        static let fromConversationsHelp = "Conversations this answer used that no page cites yet"
        static let untitledConversation = "A conversation"
        static let openConversationHint = "Click to read the conversation in the Reader"
        static func openConversationLabel(_ title: String) -> String { "Open the conversation \(title)" }
        /// While an answer is being worked out — over the still skeleton, or above the last answer (DR-43, round 3).
        static let asking = "Asking your memory…"
        /// A request that did not complete (G148): what happened and what to do, one line each.
        static let timedOut = "Ask is taking longer than expected. Ask again in a moment."
        static let unreachable = "Cicada isn't answering on this computer. Open Cicada again, then ask."
        static let cancelled = "Ask was stopped."
        static let unreadableAnswer = "Cicada couldn't read the answer. Ask again."
        static let failed = "Ask didn't finish. Ask again in a moment."
    }
}
