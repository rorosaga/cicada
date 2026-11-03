import Foundation

// G132 ruling 51f, slice 1 — the app's half of the home-network door: the Local Network permission asked at the
// person's first share or add-device click (owner D4), Bonjour on the app's side (TN3179: a launchd agent's own Bonjour
// would raise the alert under no app's name), the network hints, and the route each device is using in words. The
// decisions are here, pure, so `LocalNetworkTests` checks them without a socket.

/// `GET /sync/discovery`: what this computer advertises and browses for, while its memory is shared (404 otherwise).
struct DiscoveryPlan: Decodable, Equatable, Sendable {
    struct Advertise: Decodable, Equatable, Sendable {
        let name: String
        let port: Int
        let door: Bool

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = try c.decode(String.self, forKey: .name)
            port = try c.decode(Int.self, forKey: .port)
            door = try c.decodeIfPresent(Bool.self, forKey: .door) ?? false
        }

        init(name: String, port: Int, door: Bool) {
            self.name = name
            self.port = port
            self.door = door
        }

        private enum CodingKeys: String, CodingKey { case name, port, door }
    }

    let type: String
    /// The instance name this memory's devices advertise (`c-<hash>`, never a name or the bank id).
    let browse: String
    let advertise: Advertise?
}

/// `GET /sync/routes`: this computer's routes to its home as kinds and states, the door here, never an address.
struct SyncRoutes: Decodable, Equatable, Sendable {
    struct ToHome: Decodable, Equatable, Sendable {
        struct Route: Decodable, Equatable, Sendable {
            let kind: String
            let state: String
        }

        /// `lan`, `tailnet`, `configured`, `relay`; nil before any answered.
        let active: String?
        let queued: Bool
        let routes: [Route]

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            active = try c.decodeIfPresent(String.self, forKey: .active)
            queued = try c.decodeIfPresent(Bool.self, forKey: .queued) ?? false
            routes = try c.decodeIfPresent([Route].self, forKey: .routes) ?? []
        }

        init(active: String?, queued: Bool, routes: [Route] = []) {
            self.active = active
            self.queued = queued
            self.routes = routes
        }

        private enum CodingKeys: String, CodingKey { case active, queued, routes }
    }

    let toHome: ToHome
    let lanDial: Bool

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        toHome = try c.decodeIfPresent(ToHome.self, forKey: .toHome) ?? ToHome(active: nil, queued: false)
        lanDial = try c.decodeIfPresent(Bool.self, forKey: .lanDial) ?? false
    }

    init(toHome: ToHome, lanDial: Bool = false) {
        self.toHome = toHome
        self.lanDial = lanDial
    }

    private enum CodingKeys: String, CodingKey { case toHome, lanDial }
}

/// A door the app's Bonjour resolved (`POST /sync/discovered` `doors`): an address and a port, checked by the backend's
/// own handshake before it is kept. Never shown.
struct FoundDoor: Hashable, Sendable {
    let host: String
    let port: Int
}

enum LanRules {
    static let serviceType = "_cicada._tcp"

    /// Only an address the backend may keep: IPv4 private (RFC 1918) or IPv6 unique-local — never a link-local, public
    /// or loopback one (the backend checks again; this keeps what is posted small and honest).
    static func usable(_ host: String) -> Bool {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false).compactMap { UInt8($0) }
        if parts.count == 4, host.split(separator: ".", omittingEmptySubsequences: false).count == 4 {
            switch (parts[0], parts[1]) {
            case (10, _): return true
            case (172, 16...31): return true
            case (192, 168): return true
            default: return false
            }
        }
        let lower = host.lowercased()
        guard lower.contains(":"), !lower.contains("%") else { return false }
        return lower.hasPrefix("fc") || lower.hasPrefix("fd")
    }

    /// This memory's instance, or the same name mDNS renamed on a conflict ("c-… (2)": every device of one memory
    /// advertises the one name).
    static func matches(_ name: String, instance: String) -> Bool {
        name == instance || (name.hasPrefix(instance + " (") && name.hasSuffix(")"))
    }

    /// What is posted: the usable addresses of the instances whose name is this memory's, each with its port, at most
    /// the backend's 16, sorted so the same set posts the same body.
    static func doors(_ resolved: [(name: String, host: String, port: Int)], instance: String) -> [FoundDoor] {
        let kept = Set(resolved.filter { matches($0.name, instance: instance) && (1...65535).contains($0.port) && usable($0.host) }
            .map { FoundDoor(host: $0.host, port: $0.port) })
        return Array(kept.sorted { ($0.host, $0.port) < ($1.host, $1.port) }.prefix(16))
    }

    /// The route a device is using, as one word on its row (never an address or a port): this computer's own route
    /// to its home (`/sync/routes`' `active`), or how a device last reached this one (`/devices/status`' `how`).
    static func routeWord(_ kind: String?) -> String? {
        switch kind {
        case "lan": Copy.LocalNetwork.sameNetwork
        case "tailnet", "tailscale": Copy.LocalNetwork.tailscale
        case "configured": Copy.LocalNetwork.yourAddress
        case "relay": Copy.LocalNetwork.relay
        default: nil
        }
    }
}

/// When a network hint goes to the backend (`POST /sync/network`): a network change after it settled, an app return
/// at most once per `CicadaTiming.networkReturnEvery`. Pure, so the debounce is tested without a clock.
struct NetworkHintGate {
    enum Event: String { case changed, returned }

    private(set) var lastSent: [Event: Date] = [:]

    func due(_ event: Event, now: Date) -> Bool {
        guard let last = lastSent[event] else { return true }
        let every = event == .returned ? CicadaTiming.networkReturnEvery : CicadaTiming.networkChangeSettle
        return now.timeIntervalSince(last) >= every
    }

    mutating func sent(_ event: Event, at now: Date) { lastSent[event] = now }
}

/// The last Local Network answer this app saw (macOS offers no preflight for it): `notYet` until the person's first
/// share or add-device click asked. Hyrum: one new key, `cicada.permission.localNetwork` (`granted` | `denied`).
struct LocalNetworkMemory {
    static let key = "cicada.permission.localNetwork"
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    var state: MacPermissionState {
        switch defaults.string(forKey: Self.key) {
        case "granted": .granted
        case "denied": .denied
        default: .notYet
        }
    }

    /// Whether the person has been asked at all — the first-share step shows until they have.
    var asked: Bool { state != .notYet }

    func note(_ state: MacPermissionState) {
        switch state {
        case .granted: defaults.set("granted", forKey: Self.key)
        case .denied: defaults.set("denied", forKey: Self.key)
        case .notYet: defaults.removeObject(forKey: Self.key)
        }
    }
}

/// How a probe that ran reads (`LanDiscovery.probe`): the app's own throwaway instance came back in its browse →
/// granted; the browse is refused by policy and never found it → denied; anything else → no answer yet.
enum LocalNetworkVerdict {
    static func state(foundSelf: Bool, policyDenied: Bool, finished: Bool) -> MacPermissionState? {
        if foundSelf { return .granted }
        if finished { return policyDenied ? .denied : nil }
        return nil
    }
}
