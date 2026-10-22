import Foundation

/// G212 — the Sleep page's machines strip.
extension Copy {
    enum Machines {
        static let local = "Local"
        static let lan = "Local network"
        static let connected = "Connected"
        static let notConnected = "Not connected"
        static func waiting(_ n: Int) -> String { "\(UsageFormat.count(n)) waiting" }
        static func openQueue(_ name: String) -> String { "Show what waits from \(name)" }
        static let allMachines = "Show every machine's queue"
    }
}
