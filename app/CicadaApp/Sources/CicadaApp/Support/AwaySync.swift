import Foundation
import Observation

// G229 (owner 2026-11-03: "i knew some stuff from sources like messages, claude conversations and such where going to
// be pending but there is no syncing indicator that lets me know that") — the catch-up the app does when it opens
// after being closed: which of its readers are still reading, roughly how much has come in, and that it is done.
//
// The backend holds it (`PUT /sources/catch-up`, `api/services/reader_catch_up.py`) so every client reads one answer
// as each machine's `catchUp` on `GET /devices/status`; the app is the one that knows what its readers do, so it
// reports, and the bank — not the app — counts what came in (a harness capture the backend took while the app was
// closed included).

/// One reader on the wire: `reading`, `done`, or `failed` with the reader's own sentence naming the fix.
struct AwaySyncReader: Codable, Equatable, Hashable {
    var channel: String
    var label: String
    var state: String
    var fix: String?

    static let reading = "reading", done = "done", failed = "failed"
}

/// A machine's catch-up as the backend answers it (`reader_catch_up.views`).
struct MachineAwaySync: Codable, Equatable {
    /// `reading` or `done`.
    var state: String
    var openedAt: String?
    var awaySince: String?
    var doneAt: String?
    var readers: [AwaySyncReader]
    /// Waiting conversations whose file came in or changed while the app was closed; nil on a first launch.
    var arrived: Int?
    /// Waiting conversations that came in since the app opened (frozen when the catch-up ended).
    var newCount: Int

    enum CodingKeys: String, CodingKey { case state, openedAt, awaySince, doneAt, readers, arrived, newCount = "new" }

    init(state: String, openedAt: String? = nil, awaySince: String? = nil, doneAt: String? = nil,
         readers: [AwaySyncReader] = [], arrived: Int? = nil, newCount: Int = 0) {
        self.state = state; self.openedAt = openedAt; self.awaySince = awaySince; self.doneAt = doneAt
        self.readers = readers; self.arrived = arrived; self.newCount = newCount
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "done"
        openedAt = try c.decodeIfPresent(String.self, forKey: .openedAt)
        awaySince = try c.decodeIfPresent(String.self, forKey: .awaySince)
        doneAt = try c.decodeIfPresent(String.self, forKey: .doneAt)
        readers = try c.decodeIfPresent([AwaySyncReader].self, forKey: .readers) ?? []
        arrived = try c.decodeIfPresent(Int.self, forKey: .arrived)
        newCount = try c.decodeIfPresent(Int.self, forKey: .newCount) ?? 0
    }

    var isReading: Bool { state == "reading" }
    func labels(_ state: String) -> [String] { readers.filter { $0.state == state }.map(\.label) }
    var failures: [AwaySyncReader] { readers.filter { $0.state == AwaySyncReader.failed } }
}

/// What the app sends: its whole word, every time (an idempotent PUT, so a retry or a lost answer costs nothing).
struct AwaySyncReport: Equatable {
    var session: String
    var openedAt: Date
    var awaySince: Date?
    var readers: [AwaySyncReader]
    var done: Bool

    var body: [String: Any] {
        var out: [String: Any] = [
            "session": session, "openedAt": Self.iso(openedAt), "done": done,
            "readers": readers.map { r -> [String: Any] in
                var row: [String: Any] = ["channel": r.channel, "label": r.label, "state": r.state]
                if let fix = r.fix { row["fix"] = fix }
                return row
            },
        ]
        if let awaySince { out["awaySince"] = Self.iso(awaySince) }
        return out
    }

    static func iso(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.string(from: date)
    }
}

/// What one reader is doing right now, as its own state says it (`AwaySyncProbes.live`).
enum ReaderPhase: Equatable {
    case idle, reading
    case failed(String)
}

struct ReaderProbe: Equatable {
    let channel: String
    let label: String
    let phase: ReaderPhase
}

/// When the app was last open, kept by the app itself (per viewer: it is this app's own fact). Stamped once a minute
/// while it runs, so a quit or a crash leaves the last minute it was alive.
struct AppPresence {
    static let key = "cicada.app.lastOpenAt"
    let defaults: UserDefaults

    func last() -> Date? {
        let t = defaults.double(forKey: Self.key)
        return t > 0 ? Date(timeIntervalSince1970: t) : nil
    }

    func stamp(_ date: Date) { defaults.set(date.timeIntervalSince1970, forKey: Self.key) }
}

/// The catch-up's rules, pure (`AwaySyncTests`): which readers it lists, and when it is over.
///
/// * A reader is listed once it has been seen reading (then `done` when it stops), or when it is failing or refused —
///   a source that could not be read was not caught up, and the row says the fix. One never seen reading is not
///   listed: it had nothing to catch up on (off, or nothing new).
/// * It is over when nothing reads, at least `settle` after the backend first heard of it (readers arm one by one
///   after launch), and `quiet` after the last reader stopped. Once over it stays over: a reader that starts later is
///   the app's ordinary reading, shown on its own Sources row.
struct AwaySyncRules: Equatable {
    static let settle: TimeInterval = 10
    static let quiet: TimeInterval = 3

    private(set) var seen: Set<String> = []
    private(set) var order: [String] = []
    private(set) var lastReadingAt: Date?
    private(set) var done = false

    mutating func readers(_ probes: [ReaderProbe], now: Date) -> [AwaySyncReader] {
        var out: [AwaySyncReader] = []
        for probe in probes {
            switch probe.phase {
            case .reading:
                if seen.insert(probe.channel).inserted { order.append(probe.channel) }
                lastReadingAt = now
                out.append(AwaySyncReader(channel: probe.channel, label: probe.label, state: AwaySyncReader.reading))
            case .failed(let fix):
                out.append(AwaySyncReader(channel: probe.channel, label: probe.label, state: AwaySyncReader.failed,
                                         fix: fix))
            case .idle:
                if seen.contains(probe.channel) {
                    out.append(AwaySyncReader(channel: probe.channel, label: probe.label, state: AwaySyncReader.done))
                }
            }
        }
        // First seen first, so a list never reshuffles as readers finish.
        let rank = Dictionary(uniqueKeysWithValues: order.enumerated().map { ($1, $0) })
        return out.enumerated().sorted { a, b in
            (rank[a.element.channel] ?? Int.max, a.offset) < (rank[b.element.channel] ?? Int.max, b.offset)
        }.map(\.element)
    }

    mutating func settle(_ readers: [AwaySyncReader], heardAt: Date?, now: Date) -> Bool {
        guard !done else { return true }
        guard let heardAt, !readers.contains(where: { $0.state == AwaySyncReader.reading }) else { return false }
        guard now.timeIntervalSince(heardAt) >= Self.settle else { return false }
        if let last = lastReadingAt, now.timeIntervalSince(last) < Self.quiet { return false }
        done = true
        return true
    }
}

/// The app's one catch-up after launch: reads its readers once a second until it is over, reports each change to the
/// backend, and keeps the backend's answer for the Sleep page and Home. Stamps `AppPresence` once a minute for as long
/// as the app runs. A wait and a poll, never motion.
@MainActor
@Observable
final class AwaySyncTracker {
    /// The backend's answer for this machine; nil before it answered, and again once a finished catch-up has been
    /// shown for `shownAfterDone`.
    private(set) var view: MachineAwaySync?

    static let shownAfterDone: TimeInterval = 10 * 60
    /// While a catch-up reads, the backend hears from the app at least this often (its silence limit is 15 min).
    static let keepAlive: TimeInterval = 60

    @ObservationIgnored private var probe: @MainActor () -> [ReaderProbe]
    @ObservationIgnored private let send: (AwaySyncReport) async throws -> MachineAwaySync?
    @ObservationIgnored private let presence: AppPresence
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let tick: Duration
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var rules = AwaySyncRules()
    @ObservationIgnored private(set) var report: AwaySyncReport?
    @ObservationIgnored private var lastSent: AwaySyncReport?
    @ObservationIgnored private var lastSentAt: Date?
    @ObservationIgnored private var heardAt: Date?
    @ObservationIgnored private var doneAt: Date?
    @ObservationIgnored private var failedAt: Date?

    init(probe: @escaping @MainActor () -> [ReaderProbe] = { [] },
         send: @escaping (AwaySyncReport) async throws -> MachineAwaySync? = { try await APIClient.shared.putCatchUp($0) },
         defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init, tick: Duration = .seconds(1)) {
        self.probe = probe; self.send = send; self.presence = AppPresence(defaults: defaults)
        self.now = now; self.tick = tick
    }

    /// Once per launch (a reopened window calls it again and changes nothing). Reads when the app was last open
    /// BEFORE the first stamp, so the window it counts is the one the app was closed for.
    func start(probe: (@MainActor () -> [ReaderProbe])? = nil) {
        guard task == nil else { return }
        if let probe { self.probe = probe }
        let opened = begin()
        task = Task { [weak self] in
            var stamped = opened
            while !Task.isCancelled {
                guard let self else { return }
                await self.step()
                // Once over and shown, only the presence stamp is left to do: look again a minute later, not each second.
                try? await Task.sleep(for: self.finished ? .seconds(Self.stampEvery) : self.tick)
                let at = self.now()
                if at.timeIntervalSince(stamped) >= Self.stampEvery {
                    self.presence.stamp(at)
                    stamped = at
                }
            }
        }
    }

    /// The launch's report, with when the app was last open read before this launch stamps over it (tests call it
    /// without the loop and drive `step()` themselves).
    @discardableResult
    func begin() -> Date {
        let opened = now()
        report = AwaySyncReport(session: UUID().uuidString, openedAt: opened, awaySince: presence.last(),
                                readers: [], done: false)
        presence.stamp(opened)
        return opened
    }

    static let stampEvery: TimeInterval = 60
    /// A refused or unanswered report (the backend still starting, a demo memory's 409) is tried again this often.
    static let retryAfter: TimeInterval = 5

    /// Over, and its line no longer shown: nothing left to look at.
    var finished: Bool { lastSent?.done == true && view == nil }

    func stop() {
        task?.cancel()
        task = nil
    }

    /// One look at the readers; sends when the word changed (or a keep-alive is due), and settles the shown line.
    func step() async {
        let at = now()
        if let doneAt, at.timeIntervalSince(doneAt) >= Self.shownAfterDone {
            view = nil
            return
        }
        guard var current = report, lastSent?.done != true else { return }
        current.readers = rules.readers(probe(), now: at)
        current.done = rules.settle(current.readers, heardAt: heardAt, now: at)
        report = current
        let due = lastSentAt.map { at.timeIntervalSince($0) >= Self.keepAlive } ?? true
        guard current != lastSent || due else { return }
        if let failed = failedAt, at.timeIntervalSince(failed) < Self.retryAfter { return }
        do {
            let answer = try await send(current)
            lastSent = current
            lastSentAt = at
            failedAt = nil
            if heardAt == nil { heardAt = at }
            view = answer
            if current.done { doneAt = at }
        } catch {
            // The backend is not up yet, or refused (a demo memory, 409): try again shortly. Nothing shows meanwhile.
            failedAt = at
        }
    }
}

/// G229 — every reader the app runs, as one list of probes (`AwaySyncTracker`'s eyes). Each phase comes from the state
/// the reader already keeps for its Sources row — `SyncActivity`'s runs, the watch lights and their errors, Calendar's,
/// Notes' and Reminders' own status — so the catch-up and the row can never say two different things.
@MainActor
enum AwaySyncProbes {
    static func live(store: Store, activity: SyncActivity, lights: BrowserWatcher, calendar: CalendarReader,
                     notes: AppleNotesWatcher, reminders: RemindersReader, contacts: ContactsReader) -> [ReaderProbe] {
        let channels = store.channels.value ?? []
        let labels = Dictionary(channels.map { ($0.id, $0.label) }, uniquingKeysWith: { a, _ in a })
        var ids: [String] = channels.map(\.id)
        for id in activity.runs.keys.sorted() + lights.externalStates.keys.sorted()
            + [CalendarRow.channelId, AppleNotesWatcher.channel, RemindersReader.channel, ContactsReader.channel]
            where !ids.contains(id) {
            ids.append(id)
        }
        var out: [ReaderProbe] = []
        for id in ids where !id.hasPrefix("intake:") {
            let phase = Self.phase(id, activity: activity, lights: lights, calendar: calendar.status,
                                   notes: notes.status, reminders: reminders.status, contacts: contacts.status)
            if phase == .idle && !(labels[id] != nil || activity.run(for: id) != nil) { continue }
            out.append(ReaderProbe(channel: id, label: labels[id] ?? fallbackLabel(id), phase: phase))
        }
        return out
    }

    static func phase(_ id: String, activity: SyncActivity, lights: BrowserWatcher, calendar: CalendarReader.Status,
                      notes: AppleNotesWatcher.Status, reminders: RemindersReader.Status,
                      contacts: ContactsReader.Status) -> ReaderPhase {
        if activity.run(for: id) != nil { return .reading }
        switch id {
        case CalendarRow.channelId:
            switch calendar {
            case .syncing: return .reading
            case .denied: return .failed(Copy.calendarDenied)
            case .failed(let why): return .failed(why)
            default: return .idle
            }
        case AppleNotesWatcher.channel:
            switch notes {
            case .syncing: return .reading
            case .failed(let why): return .failed(why)
            default: return .idle
            }
        case RemindersReader.channel:
            switch reminders {
            case .syncing: return .reading
            case .denied: return .failed(Copy.remindersDenied)
            case .failed(let why): return .failed(why)
            default: return .idle
            }
        case ContactsReader.channel:
            switch contacts {
            case .syncing: return .reading
            case .denied: return .failed(Copy.contactsDenied)
            case .failed(let why): return .failed(why)
            default: return .idle
            }
        default:
            switch lights.state(for: id) {
            case .syncing?: return .reading
            case .blocked?, .failed?:
                return .failed(lights.error(for: id)?.userMessage ?? Copy.AwaySync.seeItsRow)
            default: return .idle
            }
        }
    }

    /// A reader the channel list has not named yet (the list loads after launch): its id, readable.
    static func fallbackLabel(_ id: String) -> String {
        switch id {
        case CalendarRow.channelId: "Calendar"
        case AppleNotesWatcher.channel: "Notes"
        case RemindersReader.channel: "Reminders"
        case ContactsReader.channel: "Contacts"
        case MessagesWatcher.channel: "Messages"
        case WhatsAppWatcher.channel: "WhatsApp"
        default:
            id.split(separator: ":").last.map { $0.replacingOccurrences(of: "-", with: " ").capitalized } ?? id
        }
    }
}

/// The words, pure (`AwaySyncTests`). One quiet line — what is still being read and how much has come in, or that it is
/// done — then one line per source that could not be read, its first clause in `warning` (DR-7) and the reader's own
/// sentence naming the fix.
enum AwaySyncWords {
    struct Failure: Equatable {
        let channel: String
        let lead: String
        let fix: String?
    }

    /// The main line. `machine` names another machine ("studio is syncing Messages…"); nil for this one. "Syncing", the
    /// word a Sources row already says while its reader runs ("Syncing now"), so the two never describe one read two
    /// ways — and never "catching up", which Home's *Catch me up* chat already is.
    static func line(_ c: MachineAwaySync, machine: String? = nil, locale: Locale = .autoupdatingCurrent) -> String {
        var main: String
        if c.isReading {
            let names = list(c.labels(AwaySyncReader.reading), locale)
            main = Copy.AwaySync.syncing(names, machine: machine)
            main += c.newCount > 0 ? " — \(Copy.AwaySync.newSoFar(c.newCount, locale))" : "…"
        } else {
            let names = list(c.labels(AwaySyncReader.done), locale)
            main = Copy.AwaySync.synced(names, machine: machine)
            main += c.newCount > 0 ? " — \(Copy.AwaySync.new(c.newCount, locale))"
                : (names.isEmpty ? "." : " — \(Copy.AwaySync.nothingNew)")
        }
        if let arrived = c.arrived, arrived > 0 {
            main += " " + Copy.AwaySync.whileAway(arrived, locale)
        }
        return main
    }

    static func failures(_ c: MachineAwaySync) -> [Failure] {
        c.failures.map { Failure(channel: $0.channel, lead: Copy.AwaySync.couldNotRead($0.label), fix: $0.fix) }
    }

    /// "Messages", "Messages and Notes", "Messages, Notes and Calendar", "Messages, Notes and 2 more".
    static func list(_ names: [String], _ locale: Locale = .autoupdatingCurrent) -> String {
        switch names.count {
        case 0: return ""
        case 1: return names[0]
        case 2: return "\(names[0]) and \(names[1])"
        case 3: return "\(names[0]), \(names[1]) and \(names[2])"
        default: return "\(names[0]), \(names[1]) and \(UsageFormat.count(names.count - 2, locale: locale)) more"
        }
    }

    /// Whose catch-up lines the Sleep page draws: this machine's from the tracker's fresher answer when it has one
    /// (else its own row), then every other machine catching up, by name.
    static func machines(own: MachineAwaySync?, rows: [MachineStatus]) -> [(name: String?, catchUp: MachineAwaySync)] {
        var out: [(name: String?, catchUp: MachineAwaySync)] = []
        if let mine = own ?? rows.first(where: \.current)?.catchUp { out.append((nil, mine)) }
        for row in rows where !row.current {
            if let other = row.catchUp { out.append((row.name, other)) }
        }
        return out
    }
}
