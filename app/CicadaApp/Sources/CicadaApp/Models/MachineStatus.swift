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

    var id: String { deviceId ?? "server" }

    enum CodingKeys: String, CodingKey { case deviceId = "id", name, role, connected, how, lastSeenAt, queue }

    init(deviceId: String?, name: String, role: String = "device", connected: Bool, how: String?,
         lastSeenAt: String? = nil, queue: Int) {
        self.deviceId = deviceId; self.name = name; self.role = role; self.connected = connected; self.how = how
        self.lastSeenAt = lastSeenAt; self.queue = queue
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
    /// "<name> · Tailscale · 160 waiting" — the name, how, and the count only when something waits.
    static func line(_ machine: MachineStatus) -> String {
        var parts = [machine.name]
        if let how = machine.howWord { parts.append(how) }
        if machine.queue > 0 { parts.append(Copy.Machines.waiting(machine.queue)) }
        return parts.joined(separator: " · ")
    }

    /// The Waiting list, narrowed to one machine's queue when one is open.
    static func episodes(_ all: [EpisodeQueueItem], machine: MachineStatus?) -> [EpisodeQueueItem] {
        guard let machine else { return all }
        return all.filter(machine.owns)
    }
}
