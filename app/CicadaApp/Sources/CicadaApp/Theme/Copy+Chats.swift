import Foundation

/// G179 (2026-10-28) — WhatsApp on the Sources page. Provider-neutral: nothing here names who reads.
extension Copy {
    enum Chats {
        static let whatsAppTitle = "WhatsApp"
        static let whatsAppWhatItReads = "Cicada reads only the chats you tick here — group chats included — from WhatsApp "
            + "on this Mac: each message's words, who sent it and when, which message it replies to, and the names of "
            + "attachments, never the files. A tick reads what's said from now on; ask for a chat's history to read "
            + "what WhatsApp already keeps. macOS lets an app open WhatsApp's chats only with Full Disk Access."
        static let rowLineNone = "Pick the chats Cicada should remember"
        static func rowLine(ticked: Int) -> String { ticked == 1 ? "Remembering 1 chat" : "Remembering \(ticked) chats" }
        static let choose = "Choose…"
        static let chooseHelp = "Pick which chats Cicada reads"
        static let refresh = "Refresh"
        static let done = "Done"
        static let tryAgain = "Try again"
        static let loading = "Looking for chats…"
        static let noneFound = "No chats found."
        static let whatsAppMissing = "WhatsApp for Mac isn't on this Mac, or hasn't kept any chats yet."
        static let whatsAppUnreadable = "Cicada couldn't read WhatsApp's chats on this Mac."
        static let whatsAppStalled = "Cicada stopped reading a WhatsApp chat: its newest messages couldn't be reached. "
            + "Refresh to try again."
        static let syncFailed = "Couldn't send the chat to Cicada."
        static let tickFirst = "Tick a chat first."
        static let reading = "Reading chats…"
        static let upToDate = "Up to date"
        static func synced(_ n: Int) -> String { n == 1 ? "1 message read" : "\(n) messages read" }
        static let unnamed = "Unnamed chat"
        static let group = "Group"
        static let readHistory = "Read history"
        static let readHistoryHelp = "Read what this chat already holds, back to its first message"
        static let historyAsked = "History read"
        static let tickHelp = "Remember this chat from now on"
        static func meta(last: String?, group: Bool) -> String {
            [group ? Copy.Chats.group : nil, last].compactMap { $0 }.joined(separator: " · ")
        }
    }
}
