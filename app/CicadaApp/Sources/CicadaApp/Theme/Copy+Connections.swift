import Foundation

/// Ruling 36 D6 / G217 — the words of Settings → Intelligence, You's profiles, Devices and the Agents page. The owner's
/// bar (2026-10-22): less text everywhere, Settings under 400 words, a status is a dot and one word. Provider names
/// appear only where they show the person's own choice or name the row's own product (CLAUDE.md, provider-neutral copy).
extension Copy {
    enum Status {
        static let connected = "Connected"
        static let on = "On"
        static let off = "Off"
        static let saved = "Saved"
        static let active = "Active"
        static let seen = "Seen"
        static let waiting = "Waiting"
        static let paired = "Paired"
        /// Installed or detected, not wired (ruling 39, 2026-10-24). Onboarding, the Agents page, Sources, Devices
        /// and Settings → Intelligence say it in this word; "Found" and "Not set up" are never a status.
        static let notConnected = "Not connected"
    }

    /// The one status rule for an agent or a paired device (fix round 2026-10-22; words ruling 39, 2026-10-24): the dot
    /// and the word agree. *Connected* (green) when seen within the backend's window, or when configured, when it
    /// brought conversations, or when it was ever seen — recency lives in its line ("3 min ago", "last seen Oct 21"),
    /// never in the dot's colour; *Not connected* (grey) otherwise. `.idle` only picks the line's wording.
    enum Presence: Equatable {
        case connected, idle, notConnected

        static let recentSeconds: TimeInterval = 600

        static func of(seen: Date?, configured: Bool, conversations: Int, now: Date = Date()) -> Presence {
            if let seen, now.timeIntervalSince(seen) <= recentSeconds { return .connected }
            return configured || conversations > 0 || seen != nil ? .idle : .notConnected
        }

        var word: String {
            switch self {
            case .connected, .idle: Status.connected
            case .notConnected: Status.notConnected
            }
        }

        var on: Bool { self != .notConnected }
    }

    enum Intelligence {
        static let title = "Intelligence"
        static let inUse = "In use"
        static let auto = "Auto"
        static let useAuto = "Use Auto"
        static let plans = "Plans"
        /// G49/G50 — the person's own agent tools, each signed in through itself.
        static let ownTools = "Your agent tools"
        static let notInstalled = "Not installed"
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
        static let pairScan = "Scan with Cicada on your phone"
        static let kindPhone = "Phone"
        static let kindComputer = "Computer"
        static let kindLabel = "What you are pairing"
        static let serveLead = "To pair by scanning, run this once:"
        static let newCode = "Make a new code"
        static let cancel = "Cancel"
        static let tooMany = "Five codes already wait. Cancel one first."
        static let expired = "This code expired."
        /// While the QR carries no address (the backend could not tell this machine's tailnet name).
        static let noAddress = "On the device, type the address you reach this Mac at, e.g. its Tailscale name."
        static let apps = "Apps outside this machine"
        static func waiting(_ n: Int) -> String { n == 1 ? "1 waiting" : "\(n) waiting" }
        /// 2026-10-29: a device's rights and key, each one word in its row (DR-38: said once).
        static let captureOnly = "Capture only"
        static let fullAccess = "Full access"
        static let keyBound = "Key-bound"
        static let notKeyBound = "Not yet key-bound"
        static func keyBoundSince(_ date: Date) -> String {
            "Key-bound since \(date.formatted(.dateTime.month(.abbreviated).day()))"
        }
        /// Review 2026-10-29: a device just paired under a name an older, still-active row carries.
        static func olderTwin(_ name: String) -> String { "An older \u{201C}\(name)\u{201D} is still paired." }
        static let revokeOlder = "Revoke the older one"

        /// 2026-10-29 — the guided reach step: one state line and one next step, never a tutorial. Tailscale is named
        /// because it is the person's own overlay (the row's own product), never as the one doing Cicada's job.
        enum Reach {
            static let title = "Reach from your phone"
            static let check = "Check again"
            static let checking = "Checking…"
            static let getTailscale = "Get Tailscale"
            static let downloadURL = URL(string: "https://tailscale.com/download")!
            static let ready = "Your phone can reach this Mac."
            static func readyAt(_ url: String) -> String { "Your devices reach this Mac at \(url)." }

            /// The one next step for each `reach.GUIDE_STEPS` word.
            static func step(_ step: String) -> String {
                switch step {
                case "install": "Install Tailscale on this Mac and your phone, signed in to the same account."
                case "open": "Open Tailscale on this Mac."
                case "sign-in": "Sign in to Tailscale on this Mac."
                case "turn-on": "Tailscale is off on this Mac. Turn it on from its menu."
                case "serve": "Run this once in Terminal. It stays private to your own devices:"
                case "unfunnel": "This Mac's Cicada is open to the internet. Close it with:"
                case "ready": "Your devices reach this Mac on Tailscale."
                default: "Cicada could not read Tailscale's state."
                }
            }

            /// Where the live check stopped (`reach.CHECK_FAILURES`), and what to do about it.
            static func failed(_ failed: String) -> String {
                switch failed {
                case "dns": "Stopped at the name: turn on MagicDNS in your Tailscale admin console."
                case "overlay": "Stopped at Tailscale: the name was found but nothing answered. Turn on HTTPS "
                    + "certificates in your Tailscale admin console, then check again."
                case "backend": "Stopped at Cicada: Tailscale answered but did not reach Cicada behind it."
                case "not-cicada": "Something other than Cicada answers at that address."
                case "other-cicada": "Another Cicada answers at that address, not this one."
                default: "The check did not finish. Try again."
                }
            }
        }
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
        /// "last seen Oct 21" — the day, for a row that is set up but not connected now.
        static func lastSeen(_ date: Date) -> String {
            "last seen \(date.formatted(.dateTime.month(.abbreviated).day()))"
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
