import Foundation

/// G212 — one machine on `GET /devices/status`: this server first (by its own Computer Name, never "this Mac"), then
/// each device by the name the person gave it, with whether it is connected, how, and what of its waits for Sleep.
struct MachineStatus: Codable, Equatable, Identifiable {
    /// nil for this server.
    var deviceId: String?
    var name: String
    var role: String
    var connected: Bool
    /// `local` | `tailscale` | `ssh` | `lan`, or nil before a device's first request.
    var how: String?
    var lastSeenAt: String?
    var queue: Int
    /// The machine whose token asked (this one).
    var current: Bool
    /// G229 — what that machine's app is catching up on after it was closed; nil when it is not.
    var catchUp: MachineAwaySync?
    /// 2026-11-24 (all additive; an older backend sends none of them and the defaults read as "nothing to say"):
    /// the machine that runs Sleep and writes this memory; whether it keeps a copy of it; how many changes its copy is
    /// behind and how many conversations it reported but has not sent (`unsent`; nil: that machine has not said — a
    /// backend without the machine-queue change (G132, 2026-11-24) never sends it, and the light then says nothing
    /// about it); a removed device whose conversations still wait keeps a row, `revoked`.
    var home: Bool
    var keepsCopy: Bool
    var behind: Int?
    var unsent: Int?
    var revoked: Bool

    var id: String { deviceId ?? "server" }

    enum CodingKeys: String, CodingKey {
        case deviceId = "id", name, role, connected, how, lastSeenAt, queue, current, catchUp
        case home, keepsCopy, behind, unsent, revoked
    }

    init(deviceId: String?, name: String, role: String = "device", connected: Bool, how: String?,
         lastSeenAt: String? = nil, queue: Int, current: Bool = false, catchUp: MachineAwaySync? = nil,
         home: Bool = false, keepsCopy: Bool = false, behind: Int? = nil, unsent: Int? = nil, revoked: Bool = false) {
        self.deviceId = deviceId; self.name = name; self.role = role; self.connected = connected; self.how = how
        self.lastSeenAt = lastSeenAt; self.queue = queue; self.current = current; self.catchUp = catchUp
        self.home = home; self.keepsCopy = keepsCopy; self.behind = behind; self.unsent = unsent; self.revoked = revoked
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        deviceId = try c.decodeIfPresent(String.self, forKey: .deviceId)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? "device"
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        how = try c.decodeIfPresent(String.self, forKey: .how)
        lastSeenAt = try c.decodeIfPresent(String.self, forKey: .lastSeenAt)
        queue = try c.decodeIfPresent(Int.self, forKey: .queue) ?? 0
        current = try c.decodeIfPresent(Bool.self, forKey: .current) ?? false
        catchUp = try c.decodeIfPresent(MachineAwaySync.self, forKey: .catchUp)
        home = try c.decodeIfPresent(Bool.self, forKey: .home) ?? false
        keepsCopy = try c.decodeIfPresent(Bool.self, forKey: .keepsCopy) ?? false
        behind = try c.decodeIfPresent(Int.self, forKey: .behind)
        unsent = try c.decodeIfPresent(Int.self, forKey: .unsent)
        revoked = try c.decodeIfPresent(Bool.self, forKey: .revoked) ?? false
    }

    /// How it connects, in one word.
    var howWord: String? {
        switch how {
        case "local": Copy.Machines.local
        case "tailscale": "Tailscale"
        case "ssh": "SSH"
        case "lan": Copy.Machines.lan
        default: nil
        }
    }

    /// Whether a waiting episode is this machine's (an episode with no device is this server's).
    func owns(_ episode: EpisodeQueueItem) -> Bool { episode.device == deviceId }
}

struct MachineStatusList: Codable, Equatable {
    var devices: [MachineStatus]
}

/// The strip's words and filter, pure (`MachinesStripTests`).
enum MachinesStrip {
    // MARK: The chips (the Sleep page's top row)

    /// The name a chip, a card's meta line and a sentence use: a removed device says so, once.
    static func displayName(_ machine: MachineStatus) -> String {
        guard machine.revoked, !machine.name.lowercased().contains("removed") else { return machine.name }
        return Copy.Machines.removedName(machine.name)
    }

    /// The light's three states. Never the accent, never alone (`help` says it in words).
    enum Light: Equatable { case ok, attention, quiet }

    /// Not heard from (or removed) is grey, whatever it last reported; a machine that is heard from is amber while it
    /// is syncing, its copy is behind, or (once a backend reports it) it holds conversations it has not sent, else green.
    static func light(_ machine: MachineStatus) -> Light {
        guard machine.connected, !machine.revoked else { return .quiet }
        let syncing = machine.catchUp?.isReading == true
        return syncing || (machine.behind ?? 0) > 0 || (machine.unsent ?? 0) > 0 ? .attention : .ok
    }

    /// Whether the machine wears the house: the backend names the home; an older one does not, and then the server is it.
    static func isHome(_ machine: MachineStatus, in machines: [MachineStatus]) -> Bool {
        machines.contains(where: \.home) ? machine.home : machine.role == "server"
    }

    /// The waiting count the chip shows after the name: nothing at zero.
    static func chipCount(_ machine: MachineStatus) -> Int? { machine.queue > 0 ? machine.queue : nil }

    /// "saga-01 — keeps a copy over Tailscale · 3 changes behind · last heard from 5 min ago" — what the light and
    /// the house mean, in words: `.help` and the VoiceOver label.
    static func help(_ machine: MachineStatus, in machines: [MachineStatus], now: Date = Date()) -> String {
        var facts: [String] = []
        let lead = isHome(machine, in: machines) ? Copy.Machines.runsSleep : machine.keepsCopy ? Copy.Machines.keepsCopy : nil
        let via = machine.role == "server" ? nil : machine.howWord.map(Copy.Machines.over)
        let first = [lead, via].compactMap { $0 }.joined(separator: " ")
        if !first.isEmpty { facts.append(first) }
        if machine.catchUp?.isReading == true { facts.append(Copy.Machines.syncing) }
        if let behind = machine.behind, behind > 0 { facts.append(Copy.Machines.changesBehind(behind)) }
        if let unsent = machine.unsent, unsent > 0 { facts.append(Copy.Machines.notSentYet(unsent)) }
        if machine.queue > 0 { facts.append(Copy.Machines.waiting(machine.queue)) }
        if machine.revoked { facts.append(Copy.Machines.removedFact) }
        else if machine.role != "server" {
            if let seen = machine.lastSeenAt.flatMap({ InboxAge.date($0) }) {
                facts.append(machine.connected ? Copy.Machines.heardFrom(SleepEyebrow.ago(seen, now: now))
                                               : Copy.Machines.lastHeardFrom(SleepEyebrow.ago(seen, now: now)))
            } else if !machine.connected {
                facts.append(Copy.Machines.neverHeard)
            }
        }
        return ([displayName(machine)] + [facts.joined(separator: " · ")].filter { !$0.isEmpty }).joined(separator: " — ")
    }

    /// The machine's name for an episode that came from it, or nil when the episode is this computer's (so a card
    /// says another machine's name and never this one's) or when there is one machine only.
    static func originName(of episode: EpisodeQueueItem, in machines: [MachineStatus]) -> String? {
        deviceName(episode.device, in: machines)
    }

    /// The same for a device id (a consolidated conversation's `device`; nil is this server's).
    static func deviceName(_ device: String?, in machines: [MachineStatus]) -> String? {
        guard machines.count > 1, let owner = machines.first(where: { $0.deviceId == device }), !owner.current else { return nil }
        return displayName(owner)
    }

    /// The Waiting list, narrowed to one machine's queue when one is open.
    static func episodes(_ all: [EpisodeQueueItem], machine: MachineStatus?) -> [EpisodeQueueItem] {
        guard let machine else { return all }
        return all.filter(machine.owns)
    }
}
