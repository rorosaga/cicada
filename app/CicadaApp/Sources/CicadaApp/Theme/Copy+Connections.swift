import Foundation

/// Ruling 36 D6 / G217 — the words of Settings → Intelligence, You's profiles, Devices and the Agents page. The owner's
/// bar (2026-10-22): less text everywhere, Settings under 400 words, a status is a dot and one word. Provider names
/// appear only where they show the person's own choice or name the row's own product (CLAUDE.md, provider-neutral copy).
extension Copy {
    enum Status {
        static let connected = "Connected"
        static let off = "Off"
        static let saved = "Saved"
        static let active = "Active"
        static let seen = "Seen"
        static let waiting = "Waiting"
        static let paired = "Paired"
    }

    enum Intelligence {
        static let title = "Intelligence"
        static let inUse = "In use"
        static let auto = "Auto"
        static let useAuto = "Use Auto"
        static let plans = "Plans"
        static let keys = "API keys"
        static let signIn = "Sign in"
        static let signOut = "Sign out"
        static let use = "Use"
        static let addKey = "Add key"
        static let pasteKey = "Paste the key"
        static let verify = "Verify"
        static let saveUnchecked = "Save without checking"
        static let remove = "Remove"
        static let cancel = "Cancel"
        static let local = "A model on this machine"
        static let pinned = "Fixed by this machine's setup."
        static let useHelp = "Read with this from the next cycle"

        /// "…a1b2 · secrets file · checked Oct 22" — the last four, where it lives, and when its provider accepted it.
        static func keyLine(hint: String?, store: String?, verifiedAt: String?) -> String {
            var parts: [String] = []
            if let hint, !hint.isEmpty { parts.append(hint.hasPrefix("…") ? hint : "…\(hint)") }
            switch store {
            case "environment": parts.append("environment")
            case "file": parts.append("secrets file")
            default: break
            }
            if let date = verifiedAt.flatMap(ISODate.parse) {
                parts.append("checked \(date.formatted(.dateTime.month(.abbreviated).day()))")
            } else {
                parts.append("not checked")
            }
            return parts.joined(separator: " · ")
        }
    }

    enum Profiles {
        static let title = "Your profiles"
        static let photo = "Photo"
        static let paste = "Paste a profile link"
        static let add = "Add"
        static let remove = "Remove"
        static let connect = "Connect"
    }

    enum DevicesPage {
        static let pair = "Pair a device"
        static let revoke = "Revoke"
        static let pairTitle = "Pair a device"
        static let pairHint = "Scan with Cicada on the other device, or type the code."
        static let newCode = "Make a new code"
        static let cancel = "Cancel"
        static let tooMany = "Five codes already wait. Cancel one first."
        static let expired = "This code expired."
        static let noAddress = "Type this machine's address on the device."
        static let apps = "Apps outside this machine"
        static func waiting(_ n: Int) -> String { n == 1 ? "1 waiting" : "\(n) waiting" }
        static func expires(_ date: Date) -> String {
            "Expires \(date.formatted(.dateTime.hour().minute()))"
        }
    }

    enum AgentsPage {
        static let title = "Agents"
        static let addToken = "Add an agent token"
        static let tokenName = "Agent name"
        static let make = "Make token"
        static let copy = "Copy"
        static let copied = "Copied"
        static let copyPrompt = "Copy setup prompt"
        static let shownOnce = "Shown once. Paste it to the agent."
        static let products = "Products"
        static let trust = "Page edits"
        static let writesAtOnce = "Writes at once"
        static let proposes = "Proposes"
        static let importExport = "Import its chat export"
        static let tokens = "Agent tokens"
        static let revoke = "Revoke"
        static let back = "Agents"
        static let remembers = "Remembers automatically"
        static let commandLine = "Command-line tool"
        static func conversations(_ n: Int) -> String { n == 1 ? "1 conversation" : "\(n) conversations" }
        static func seen(_ date: Date, now: Date = Date()) -> String {
            RelativeDateTimeFormatter().localizedString(for: date, relativeTo: now)
        }
        static func connectsWord(_ raw: String) -> String? {
            switch raw {
            case "stdio": "on this machine"
            case "remote": "from anywhere"
            case "rest": "by token"
            case "messages": "in Messages"
            case "export": "by export"
            default: nil
            }
        }
    }
}

/// ISO-8601 timestamps from the backend, with or without fractional seconds.
enum ISODate {
    static func parse(_ raw: String) -> Date? {
        let plain = ISO8601DateFormatter()
        if let date = plain.date(from: raw) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: raw)
    }
}
