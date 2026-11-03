import Foundation

/// G179 (2026-10-28) — WhatsApp and Telegram on the Sources page. Provider-neutral: nothing here names who reads.
extension Copy {
    enum Chats {
        static let whatsAppTitle = "WhatsApp"
        static let telegramTitle = "Telegram chats"
        /// 2026-11-03 — what "checked" measures (`ChatCheck`): the store on this Mac, read on every change. On the status
        /// line's hover only (owner 2026-11-03: the pickers' and pages' standing paragraphs are gone).
        static let whatsAppWhenItReads = "Cicada checks the chats you tick each time WhatsApp on this Mac saves a "
            + "message, in any chat; “checked” is the last time, “newest message” the newest one in them. A message "
            + "sent from your phone reaches Cicada once WhatsApp on this Mac has it, which it gets while it's open."
        static let telegramWhatItReads = "Cicada reads only the one-to-one chats you tick here, through your own Telegram "
            + "account: each message's words, who sent it and when, replies, reactions and edits, and the names of "
            + "attachments, never the files. A tick reads what's said from now on; ask for a chat's history to read what "
            + "Telegram keeps. Group chats and channels aren't offered: Telegram's terms need everyone's consent."
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
        /// chats-ux-v2 (owner 2026-10-29: a bare "Couldn't send the chat to Cicada." over his self-chat) — what failed
        /// and what to do, never a bare "couldn't": the backend's own sentence when it gave one, else these.
        static let syncFailed = "Cicada couldn't save this chat's messages. Refresh to try again; if it fails again, "
            + "update Cicada — this version may not read something in the chat."
        static func saveFailed(_ status: Int) -> String {
            "Cicada's backend refused this chat's messages (error \(status)). Refresh to try again; if it fails "
                + "again, update Cicada."
        }

        /// One reading of a chat failure for WhatsApp and Telegram alike: the backend's own sentence (`detail`) for any
        /// refusal that carries one, the backend-down and needs-update lines, else a sentence with the status.
        static func failure(_ error: Error) -> String {
            if error is URLError { return Copy.sourceBackendDown }
            guard let api = error as? APIError else { return syncFailed }
            switch api {
            case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
            case .httpError(let status, let body): return ProjectWriteFailure.detail(body) ?? saveFailed(status)
            case .serverUnreachable: return Copy.sourceBackendDown
            default: return syncFailed
            }
        }
        static let tickFirst = "Tick a chat first."
        static let reading = "Reading chats…"
        static let upToDate = "Up to date"
        static func synced(_ n: Int) -> String { n == 1 ? "1 message read" : "\(n) messages read" }
        static let unnamed = "Unnamed chat"
        /// chats-ux-v2 — the person's chat with themselves (WhatsApp's "message yourself").
        static let selfChat = "Notes to yourself"
        static let searchPrompt = "Search chats"
        static let searchPromptNumber = "Search by name or number"
        static func noMatches(_ query: String) -> String { "No chat matches “\(query)”." }
        static let group = "Group"
        static let readHistory = "Read history"
        static let readHistoryHelp = "Read what this chat already holds, back to its first message"
        static let historyAsked = "History read"
        static let tickHelp = "Remember this chat from now on"
        static func meta(last: String?, group: Bool) -> String {
            [group ? Copy.Chats.group : nil, last].compactMap { $0 }.joined(separator: " · ")
        }
        // Telegram's connect steps (ruling 47a). The QR is the default (owner 2026-10-29): linking a device.
        static let connect = "Connect…"
        static let connectHelp = "Link Cicada to your own Telegram account"
        static let qrHow = "Open Telegram on your phone → Settings → Devices → Link Desktop Device, and scan this code."
        static let qrRefreshes = "The code refreshes by itself until you scan it."
        static let qrAccessibility = "Telegram sign-in code"
        static let qrStarting = "Asking Telegram for a code…"
        static let qrAgain = "Show a new code"
        static let usePhone = "Use phone number instead"
        static let useQR = "Scan a code instead"
        static let phoneHow = "Telegram sends a code to the Telegram app on your phone."
        static let codeHow = "Enter the code Telegram sent to your Telegram app."
        static let passwordHow = "Your account has two-step verification. Enter its password to finish."
        static let passwordPrompt = "Password"
        /// The one line every step keeps before connecting (ruling 47a: one-to-one only, the other person's
        /// agreement); the backend's own session sentence follows it word for word.
        static let telegramFacts = "Only the one-to-one chats you tick are read, each with the other person's agreement."
        static let disconnect = "Disconnect"
        static let disconnectHelp = "End Cicada's Telegram session now — it is logged out at Telegram"
        static let notConnected = "Not connected"
        static let connected = "Connected"
        static let sessionEnded = "Session ended — connect again to keep reading"
        // The per-chat consent (ruling 47a amendment, owner 2026-10-28).
        static let consentTitle = "Did they agree?"
        static let consentYes = "They agreed"
        static let consentCancel = "Cancel"
        static let theOtherPerson = "the other person"
    }

    /// 2026-11-03 — a chat source's page: the chats Cicada holds, and one chat's stored conversation in the panel.
    enum ChatPage {
        static let today = "Today"
        static let yesterday = "Yesterday"
        static let synced = "Synced"
        static func lastSynced(_ ago: String) -> String { "Last synced \(ago)" }
        static let notSyncing = "Not syncing"
        static let pin = "Pin to Top"
        static let unpin = "Unpin"
        static let pinned = "Pinned"
        static let pinFailed = "Cicada couldn't pin this chat. Try again."
        static let openHelp = "Show this chat's messages"
        static let closeHelp = "Close the chat (Esc)"
        static let close = "Close"
        static let earlier = "Earlier messages"
        static let loading = "Loading messages…"
        static let failed = "Cicada couldn't load this chat's messages."
        static let empty = "No messages stored for this chat yet."
        /// An unticked chat: its name, picture and recency, never its words (G179's ticked-only rail).
        static let notTicked = "Cicada isn't syncing this chat, so its messages aren't shown here. Tick it in Choose… "
            + "to sync it."
        static func rowLabel(_ name: String, sync: String, recency: String?, pinned: Bool) -> String {
            [name, pinned ? pinned_ : nil, sync, recency].compactMap { $0 }.joined(separator: ", ")
        }
        private static let pinned_ = "pinned"
    }
}
