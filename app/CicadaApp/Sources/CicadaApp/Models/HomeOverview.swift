import Foundation

/// G132 phase 2 (ruling 51a) — `GET /sync/home`: the device that runs consolidation (the home, which also orders every
/// change — one concept), with its Sleep state, and every other device with whether it is online and how far behind
/// its copy is. A computer that shares nothing answers `shared: false`, and the Sleep page draws nothing new. Not a
/// Store domain: machine-wide, polled while the Sleep page shows, held in memory; a failed poll keeps the last answer.
struct HomeOverview: Decodable, Equatable {
    struct Home: Decodable, Equatable {
        var id: String?
        var name: String
        var me: Bool
        var online: Bool
        var sleep: SleepLine?
    }

    struct SleepLine: Decodable, Equatable {
        var status: String?
        var stage: Int?
        var totalStages: Int?
    }

    struct Device: Decodable, Equatable, Identifiable {
        var id: String
        var name: String
        var me: Bool
        var online: Bool
        var keepsCopy: Bool
        var behind: Int?
        var canBeHome: Bool

        enum CodingKeys: String, CodingKey { case id, name, me, online, keepsCopy, behind, canBeHome }

        init(id: String, name: String, me: Bool, online: Bool, keepsCopy: Bool, behind: Int?, canBeHome: Bool) {
            self.id = id; self.name = name; self.me = me; self.online = online; self.keepsCopy = keepsCopy
            self.behind = behind; self.canBeHome = canBeHome
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
            me = try c.decodeIfPresent(Bool.self, forKey: .me) ?? false
            online = try c.decodeIfPresent(Bool.self, forKey: .online) ?? false
            keepsCopy = try c.decodeIfPresent(Bool.self, forKey: .keepsCopy) ?? false
            behind = try c.decodeIfPresent(Int.self, forKey: .behind)
            canBeHome = try c.decodeIfPresent(Bool.self, forKey: .canBeHome) ?? false
        }
    }

    /// A line the backend wrote in words (moving, a take-over offer, what was set aside, a note).
    struct Words: Decodable, Equatable {
        var text: String?
        var phase: String?
        var possible: Bool?
        var behind: Int?
    }

    var shared: Bool
    var role: String?
    var term: Int?
    var home: Home?
    var devices: [Device]
    var moving: Words?
    var takeOver: Words?
    var setAside: Words?
    var note: Words?

    enum CodingKeys: String, CodingKey { case shared, role, term, home, devices, moving, takeOver, setAside, note }

    init(shared: Bool, role: String? = nil, term: Int? = nil, home: Home? = nil, devices: [Device] = [],
         moving: Words? = nil, takeOver: Words? = nil, setAside: Words? = nil, note: Words? = nil) {
        self.shared = shared; self.role = role; self.term = term; self.home = home; self.devices = devices
        self.moving = moving; self.takeOver = takeOver; self.setAside = setAside; self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shared = try c.decodeIfPresent(Bool.self, forKey: .shared) ?? false
        role = try c.decodeIfPresent(String.self, forKey: .role)
        term = try c.decodeIfPresent(Int.self, forKey: .term)
        home = try c.decodeIfPresent(Home.self, forKey: .home)
        devices = try c.decodeIfPresent([Device].self, forKey: .devices) ?? []
        moving = try c.decodeIfPresent(Words.self, forKey: .moving)
        takeOver = try c.decodeIfPresent(Words.self, forKey: .takeOver)
        setAside = try c.decodeIfPresent(Words.self, forKey: .setAside)
        note = try c.decodeIfPresent(Words.self, forKey: .note)
    }

    /// While the memory is moving no other move is offered (the backend refuses one anyway).
    var isMoving: Bool { moving != nil && moving?.phase != "refused" }
}

/// `POST /sync/home/move`'s 202: the move's progress as the home started it (a copy forwards the home's answer).
struct HomeMoveAnswer: Decodable, Equatable {
    var moving: HomeOverview.Words?
}

/// `GET /sync/home/take-over` — what the person is shown before they confirm a take-over.
struct TakeOverPreview: Decodable, Equatable {
    var possible: Bool
    var behind: Int?
    var text: String?
    var code: String?
}

/// The strip's words, pure (`HomeStripTests`). Provider-neutral and plain (DR-59): a device is its own name.
enum HomeStrip {
    /// "Sleep runs on <name> · this computer · idle" — who consolidates, and in what state.
    static func homeLine(_ home: HomeOverview.Home) -> String {
        var parts = [Copy.MemoryHome.runsOn(home.name)]
        if home.me { parts.append(Copy.MemoryHome.thisComputer) }
        parts.append(home.online ? sleepWord(home.sleep) : Copy.MemoryHome.notAnswering)
        return parts.joined(separator: " · ")
    }

    static func sleepWord(_ sleep: HomeOverview.SleepLine?) -> String {
        guard let sleep, sleep.status == "running" else { return Copy.MemoryHome.sleepIdle }
        if let stage = sleep.stage, let total = sleep.totalStages, total > 0 {
            return Copy.MemoryHome.sleepStage(min(stage + 1, total), total)
        }
        return Copy.MemoryHome.sleepRunning
    }

    /// "<name> · online · 3 behind" — every other device.
    static func deviceLine(_ device: HomeOverview.Device) -> String {
        var parts = [device.name]
        if device.me { parts.append(Copy.MemoryHome.thisComputer) }
        parts.append(device.online ? Copy.MemoryHome.online : Copy.MemoryHome.offline)
        parts.append(lag(device))
        return parts.joined(separator: " · ")
    }

    static func lag(_ device: HomeOverview.Device) -> String {
        guard device.keepsCopy else { return Copy.MemoryHome.noCopy }
        guard let behind = device.behind else { return Copy.MemoryHome.lagUnknown }
        return behind == 0 ? Copy.MemoryHome.upToDate : Copy.MemoryHome.behind(behind)
    }

    /// Whether "Make this the home" is offered on a row: a device that keeps a copy, can be reached, and no move is
    /// already under way.
    static func offersMove(_ device: HomeOverview.Device, in overview: HomeOverview) -> Bool {
        device.canBeHome && !overview.isMoving && overview.role != "left" && overview.role != "superseded"
    }

    /// The lines the backend wrote in words, in order: moving, a take-over offer, what was set aside, a note.
    static func notes(_ overview: HomeOverview) -> [String] {
        [overview.moving, overview.takeOver, overview.setAside, overview.note]
            .compactMap { $0?.text }.filter { !$0.isEmpty }
    }

    /// Every plain line under the strip: the move (the poll's words, else the home's answer to this computer's own
    /// request), a take-over offer, what was set aside, a note, then the last refusal.
    static func lines(_ overview: HomeOverview, movingLine: String?, problem: String?) -> [String] {
        var out: [String] = []
        if let movingLine, !movingLine.isEmpty { out.append(movingLine) }
        out += [overview.takeOver, overview.setAside, overview.note].compactMap { $0?.text }.filter { !$0.isEmpty }
        if let problem, !problem.isEmpty { out.append(problem) }
        return out
    }
}
