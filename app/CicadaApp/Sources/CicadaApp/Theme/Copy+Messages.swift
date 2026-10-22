import Foundation

/// G179 — Messages in Settings → Integrations, and the waiting bubbles on the Sleep page and Home. Provider-neutral:
/// an agent is named only by the person's own contact name for it.
extension Copy {
    enum Messages {
        static let title = "Messages"
        /// The one sentence before access (the brief: what Cicada reads, and why it needs Full Disk Access).
        static let whatItReads = "Cicada reads only the conversations you tick here — each message's words, who sent "
            + "it and when, its reactions, replies and edits, and the names of attachments, never the files — from "
            + "Messages on this Mac, which macOS lets an app open only with Full Disk Access."
        /// 2026-10-20: sittings saved before reactions, replies and attachments were kept get them only on a re-read.
        static let readAgain = "Read again"
        static let readAgainHelp = "Read your ticked conversations again from the start, to add reactions, replies, "
            + "edits and attachments to what was saved before. A conversation whose words didn't change isn't read by "
            + "Sleep again."
        static let rowLineNone = "Pick the conversations Cicada should remember"
        static func rowLine(ticked: Int) -> String {
            ticked == 1 ? "Remembering 1 conversation" : "Remembering \(ticked) conversations"
        }
        static let choose = "Choose…"
        static let chooseHelp = "Pick which conversations Cicada reads"
        static let syncNow = "Refresh"
        static let tryAgain = "Try again"
        static let done = "Done"
        static let loading = "Looking for conversations…"
        static let noneFound = "No one-to-one conversations on this Mac yet."
        static let groupsLater = "Group chats aren't read yet."
        static let unreadable = "Cicada couldn't read Messages on this Mac."
        static let syncFailed = "Couldn't send the conversation to Cicada."
        static let tickFirst = "Tick a conversation first — nothing is read until you do."
        static let reading = "Reading Messages…"
        static func sending(_ n: Int) -> String { n == 1 ? "Sending 1 message…" : "Sending \(n) messages…" }
        static func synced(_ n: Int) -> String { n == 1 ? "Synced 1 message" : "Synced \(n) messages" }
        static let upToDate = "Up to date"
        static let contactsHint = "Allow Contacts to see names and photos instead of numbers. A number is never sent to "
            + "Cicada's memory."
        static let allowContacts = "Allow Contacts"

        // The list
        static func meta(last: String?, count: Int) -> String {
            let messages = count == 1 ? "1 message" : "\(count) messages"
            guard let last else { return messages }
            return "\(last) · \(messages)"
        }
        static let tickHelp = "Remember this conversation"
        static let agentTag = "AI agent"
        static let agentTagSuggested = "AI agent · suggested"
        static let personTag = "A person"
        static func askIfAgent(_ name: String) -> String { "Is \(name) an AI agent?" }
        static let yesAgent = "Yes, an AI agent"
        static let noPerson = "No, a person"
        static let markMenu = "Who is this?"
        static let markAgent = "This is an AI agent"
        static let markPerson = "This is a person"
        static let markClear = "Let Cicada suggest"
        static let suggestAgents = "Suggest which conversations are AI agents"
        static let suggestAgentsHelp = "From the conversation's name and how much each side writes — never its words. "
            + "A suggestion only labels; it never ticks a conversation."
        static let whoIsWho = "Your messages are yours. An AI agent's replies stay the agent's — never your own words."

        // The bubbles
        static func waiting(_ n: Int) -> String { n == 1 ? "1 message" : "\(n) messages" }
        static func bubbleHelp(name: String, messages: Int) -> String {
            "\(name) · \(waiting(messages)) waiting to be read"
        }
        static let sleepRowTitle = "Messages"
        static func more(_ n: Int) -> String { "+\(n)" }
    }
}
