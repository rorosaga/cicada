import Foundation

/// G181 phase 3 — the words for where memory lives and for the person's devices (Settings →
/// Devices). DR-59: sentence case, plain verbs. Provider-neutral (owner 2026-09-30): an overlay is "your own private
/// network", never a product's name — the person's own address is the only name shown.
extension Copy {
    enum Devices {
        // MARK: Settings → Devices — where your memory lives
        static let whereGroup = "Where your memory lives"
        static let modeTitle = "Memory on"
        static let thisMac = "This Mac"
        static let aServer = "A server"
        static let thisMacDetail = "Cicada keeps your memory in a folder on this Mac and consolidates it here."
        static let serverDetail = "Your memory lives on a server you run. This Mac reads it and sends what it captures there; "
            + "nothing is kept in a memory folder here."
        static let addressTitle = "Server address"
        static let addressPlaceholder = "https://your-server.example.net"
        static let addressHelp = "The address your own private network gives the server. Use https, or http only for a "
            + "tunnel that ends on this Mac."
        static let tokenTitle = "Device token"
        static let tokenPlaceholder = "cic_dev_…"
        static let tokenHelp = "Make one on the server with `cicada device add <name>`, then paste it here. It is kept in "
            + "~/.cicada/device_token, readable only by you."
        static let tokenSaved = "A device token is saved on this Mac."
        static let deviceTokenDetail = "This Mac's device token for the server, kept in ~/.cicada/device_token. It is never shown here."
        static let tokenReplace = "Replace"
        static let check = "Check and use"
        static let checking = "Checking the server…"
        static let useThisMac = "Use this Mac"
        static let restart = "Restart Cicada"
        static let restartHelp = "Cicada closes and opens again to switch where your memory lives"
        static let restartByHand = "Quit Cicada and open it again to switch."
        static let environmentSet = "Set by CICADA_API_BASE in Cicada's environment, so it can't be changed here."
        static let backgroundNotNeeded = "Not needed while your memory lives on a server: nothing runs on this Mac for it."
        static let agentsFollow = "Agents and the cicada command on this Mac follow this choice once Cicada restarts."

        static func pendingServer(_ host: String) -> String { "Cicada will use \(host) when it opens again." }
        static let pendingThisMac = "Cicada will use this Mac when it opens again."
        static func checkedOK(_ host: String, device: String?) -> String {
            device.map { "\(host) answered and knows this Mac as \($0)." } ?? "\(host) answered and accepted the token."
        }
        static let checkUnreachable = "The server didn't answer. Check the address and that your private network is on."
        static let checkBadToken = "The server didn't accept this token. Make a new one on the server and paste it here."
        static let checkNotDevice = "That isn't a device token. Make one on the server with `cicada device add <name>`."
        static let checkNotCicada = "Something answered at that address, but it isn't a Cicada server."
        static func checkFailed(_ code: Int) -> String { "The server answered with an error (\(code))." }
        static let saveFailed = "Couldn't save the address on this Mac."

        // Address rule (runtime_layout.api_base, restated).
        static let addressNotURL = "That isn't a web address."
        static let addressNotHTTP = "The address must start with https://."
        static let addressExtras = "The address can't carry a name, password, query or fragment."
        static let addressNeedsHTTPS = "Use https, or http only for a tunnel that ends on this Mac (127.0.0.1)."

        // Errors in words.
        static let queuedOffline = "The server isn't answering, so this waits on this Mac and is sent when it is back."
        static let demoStaysLocal = "The demo runs only when your memory lives on this Mac."

        // MARK: Settings → Devices
        static let sidebar = "Devices"
        static let subtitle = "Which of your devices reach your memory"
        static let devicesGroup = "Your devices"
        static let connectionIndexTitle = "Server connection"
        static func connectionServer(_ host: String) -> String { "This app is using \(host) now." }
        static let connectionInvalid = "The server address isn't valid, so nothing is sent anywhere."
        static func reachable(_ checked: String) -> String { "Reachable · checked \(checked)" }
        static func unreachable(_ since: String?) -> String {
            since.map { "Not reachable · last answered \($0)" } ?? "Not reachable yet"
        }
        static func waiting(_ n: Int) -> String {
            n == 1 ? "1 capture waits on this Mac for the server." : "\(n) captures wait on this Mac for the server."
        }
        static let sendNow = "Send now"
        static let none = "No other device reaches this memory yet."
        static let add = "Add a device"
        static let addHelp = "Make a token for another of your devices; it is shown once"
        static let addOnServer = "Add or revoke a device on the server with `cicada device add <name>` and `cicada device revoke <id>`."
        static let revoke = "Revoke"
        static func revokeTitle(_ name: String) -> String { "Revoke \(name)?" }
        static let revokeMessage = "It stops reaching your memory right away. What it already sent stays, and still says it came from it."
        static let thisDevice = "this Mac"
        static let thisServer = "this server"
        static let aDevice = "a device"
        static func added(_ when: String) -> String { "added \(when)" }
        static func lastSeen(_ when: String) -> String { "last seen \(when)" }
        static let neverSeen = "not seen yet"
        static func revokedOn(_ when: String) -> String { "revoked \(when)" }
        static let loadFailed = "Couldn't load the devices."
        static let nameTitle = "Name"
        static let namePlaceholder = "The laptop"
        static let create = "Make token"
        static let cancel = "Cancel"
        static let done = "Done"
        static let shownOnceTitle = "Copy this token now"
        static let shownOnceDetail = "It is shown once. On that device, open Cicada → Settings → Devices → A server, and "
            + "paste this address and token. For agents without the app, put the token in ~/.cicada/device_token "
            + "(mode 0600) and set CICADA_API_BASE."
        static let copy = "Copy"
        static let copied = "Copied"

        // MARK: Provenance — one quiet word
        static func from(_ label: String) -> String { "from \(label)" }
        static func onServer(_ host: String) -> String { "on \(host)" }
    }
}
