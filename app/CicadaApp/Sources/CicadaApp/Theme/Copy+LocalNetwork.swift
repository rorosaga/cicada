import Foundation

/// G132 ruling 51f — the first-share step, the routes in words and Devices' Advanced fold. DR-59: sentence case, short,
/// said once; no address, port or variable is ever shown. "Tailscale" is the person's own overlay named as their
/// route (a choice they made), never as the one doing Cicada's job.
extension Copy {
    enum LocalNetwork {
        // The first-share step (owner D4): the act the person clicked is its title, so nothing above repeats the row.
        static let name = "Local network"
        static let unlocks = "Your devices find each other on this network"
        static let firewall = "If macOS asks about incoming connections, choose Allow."
        static let continueTitle = "Continue"

        // A route as one word (never an address or a port)
        static let sameNetwork = "Same network"
        static let tailscale = "Tailscale"
        static let yourAddress = "Your address"
        static let relay = "Relay"
        static let queued = "Queued"
        static func reached(_ date: Date, now: Date = Date()) -> String {
            // A minute timeline's `now` is the minute's start: within a minute is "just now", never "in 24 seconds".
            if now.timeIntervalSince(date) < 60 { return "reached just now" }
            return "reached \(RelativeDateTimeFormatter().localizedString(for: date, relativeTo: now))"
        }
        static let full = "Queue full: nothing waiting was lost, but new changes aren't kept until the home answers."

        // Devices' last fold (owner D9: the relay is never a default)
        static let advanced = "Advanced"
        static let relayOn = "Relay on"

        static var labels: [String] {
            [name, unlocks, firewall, continueTitle, sameNetwork, tailscale, yourAddress, relay, queued, full, advanced,
             relayOn]
        }
    }
}
