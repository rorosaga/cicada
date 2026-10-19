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
    }
}
