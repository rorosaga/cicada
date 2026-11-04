import Foundation
import Observation

/// Someone asked a vendor for their export and wants a nudge when it should
/// have arrived. A per-viewer convenience in defaults — never memory, never a
/// bank, never the network (nothing is fetched to learn that an email came).
struct ExportWait: Codable, Equatable, Identifiable {
    let vendor: String
    let bank: String
    let requestedAt: Date
    let remindAt: Date
    var id: String { "\(bank)|\(vendor)" }
}

enum ReminderDelay: String, CaseIterable, Identifiable {
    case threeHours, tomorrowMorning, twoDays
    var id: String { rawValue }

    var label: String {
        switch self {
        case .threeHours: Copy.reminderInThreeHours
        case .tomorrowMorning: Copy.reminderTomorrowMorning
        case .twoDays: Copy.reminderInTwoDays
        }
    }

    func remindAt(from now: Date, calendar: Calendar = .autoupdatingCurrent) -> Date {
        switch self {
        case .threeHours: return now.addingTimeInterval(3 * 3600)
        case .twoDays: return now.addingTimeInterval(2 * 86_400)
        case .tomorrowMorning:
            let tomorrow = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: now)) ?? now
            return calendar.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow) ?? tomorrow
        }
    }
}

/// G197 layer c (2026-11-04) — a standing weekly nudge to ask a vendor for a fresh export, so the person's own
/// export is a stream rather than a one-off seed. Same weekday the person turned it on, at 9:00 local; tapping it
/// opens that vendor's export page in the person's own browser (Cicada clicks nothing there) and opens a wait, which
/// is what arms the Downloads pickup (`ExportArrivalWatcher`). One per bank × vendor; a per-viewer convenience in
/// defaults, like the waits — never memory, never a bank, never the network.
struct ExportHabit: Codable, Equatable, Identifiable {
    let vendor: String
    let bank: String
    /// `Calendar` weekday, 1 = Sunday.
    let weekday: Int
    let hour: Int
    let minute: Int
    var id: String { "\(bank)|\(vendor)" }

    static func starting(vendor: String, bank: String, from now: Date,
                         calendar: Calendar = .autoupdatingCurrent) -> ExportHabit {
        ExportHabit(vendor: vendor, bank: bank, weekday: calendar.component(.weekday, from: now), hour: 9, minute: 0)
    }

    var dateComponents: DateComponents { DateComponents(hour: hour, minute: minute, weekday: weekday) }
}

/// Track I part b (design §5.5, R-IB22) — the pure half: one wait per bank ×
/// vendor, gone after 14 days, and the three sentences the twins show.
enum ExportWaits {
    static let defaultsKey = "cicada.exportWaits"
    static let habitsKey = "cicada.exportHabits"
    static let maxAge: TimeInterval = 14 * 86_400
    /// How often a shown "requested 2 hours ago" is recomputed (the Feed strip,
    /// Getting started) — a minute is the finest unit the formatter's lines need.
    static let refreshInterval: TimeInterval = 60

    static func adding(_ w: ExportWait, to waits: [ExportWait]) -> [ExportWait] { waits.filter { $0.id != w.id } + [w] }
    static func clearing(vendor: String, bank: String, in waits: [ExportWait]) -> [ExportWait] {
        waits.filter { !($0.vendor == vendor && $0.bank == bank) }
    }
    static func pruned(_ waits: [ExportWait], now: Date) -> [ExportWait] {
        waits.filter { now.timeIntervalSince($0.requestedAt) < maxAge }
    }
    static func active(_ waits: [ExportWait], bank: String, now: Date) -> [ExportWait] {
        pruned(waits, now: now).filter { $0.bank == bank }.sorted { $0.requestedAt < $1.requestedAt }
    }

    static func vendorTitle(_ vendor: String) -> String { ChatVendor(rawValue: vendor)?.title ?? vendor }

    static func relative(_ date: Date, now: Date, locale: Locale) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = locale
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: now)
    }

    /// The Feed strip's line. The words live in `Copy` (so the copy lint reads
    /// them); the relative times come from the system formatter on the viewer's
    /// locale, and are recomputed on every render — never stored.
    static func stripLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.reminderStripLine(vendorTitle(w.vendor), requested: relative(w.requestedAt, now: now, locale: locale))
    }
    /// The menu bar's disabled line — refreshed as the menu opens (`MenuBarManager`).
    static func menuLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.reminderMenuLine(vendorTitle(w.vendor), requested: relative(w.requestedAt, now: now, locale: locale))
    }
    /// Under the asking row (the Welcome, Getting started): when it was asked,
    /// and when the nudge comes — the reminder half drops once it has passed.
    static func rowLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        let requested = relative(w.requestedAt, now: now, locale: locale)
        guard w.remindAt > now else { return Copy.reminderRowLine(requested: requested, reminder: nil) }
        return Copy.reminderRowLine(requested: requested, reminder: relative(w.remindAt, now: now, locale: locale))
    }
}

/// The waits, persisted, and the one place a reminder is scheduled. The
/// notification permission is requested here and only here — from the person's
/// own "Remind me" — and a denial still records the wait, because the Feed,
/// the menu bar and Getting started say it without any permission.
@MainActor
@Observable
final class ExportWaitStore {
    private(set) var waits: [ExportWait]
    private(set) var habits: [ExportHabit]
    /// Called after every change to the waits — the Downloads pickup opens and closes on it (`ExportArrivalWatcher`).
    @ObservationIgnored var onChange: (() -> Void)?
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let scheduler: ReminderScheduling
    @ObservationIgnored private let now: () -> Date

    init(defaults: UserDefaults = .standard, scheduler: ReminderScheduling = LiveReminderScheduler(),
         now: @escaping () -> Date = Date.init) {
        self.defaults = defaults
        self.scheduler = scheduler
        self.now = now
        let stored = (defaults.data(forKey: ExportWaits.defaultsKey))
            .flatMap { try? JSONDecoder().decode([ExportWait].self, from: $0) } ?? []
        waits = ExportWaits.pruned(stored, now: now())
        habits = (defaults.data(forKey: ExportWaits.habitsKey))
            .flatMap { try? JSONDecoder().decode([ExportHabit].self, from: $0) } ?? []
        persist()
    }

    var anyWait: Bool { !ExportWaits.pruned(waits, now: now()).isEmpty }

    func weekly(vendor: String, bank: String) -> Bool { habits.contains { $0.vendor == vendor && $0.bank == bank } }

    /// *Every week*: the habit is recorded whatever the permission says (the menu says it is on), and scheduled only
    /// with it — the same rule as `remind`. `false` when notifications are off.
    @discardableResult
    func startWeekly(vendor: String, bank: String) async -> Bool {
        let habit = ExportHabit.starting(vendor: vendor, bank: bank, from: now())
        habits = habits.filter { $0.id != habit.id } + [habit]
        persistHabits()
        guard await scheduler.requestPermission() else { return false }
        await scheduler.scheduleWeekly(habit)
        return true
    }

    func stopWeekly(vendor: String, bank: String) {
        for h in habits where h.vendor == vendor && h.bank == bank { scheduler.cancelWeekly(h) }
        habits = habits.filter { !($0.vendor == vendor && $0.bank == bank) }
        persistHabits()
    }

    /// The weekly nudge was tapped: the person is about to ask for the export, so a wait opens — its reminder the
    /// next morning, as if they had chosen it — and with it the Downloads pickup.
    func weeklyTapped(vendor: String, bank: String) async {
        _ = await remind(vendor: vendor, bank: bank, delay: .tomorrowMorning)
    }

    func active(bank: String) -> [ExportWait] { ExportWaits.active(waits, bank: bank, now: now()) }

    @discardableResult
    func remind(vendor: String, bank: String, delay: ReminderDelay) async -> Bool {
        let at = now()
        let wait = ExportWait(vendor: vendor, bank: bank, requestedAt: at, remindAt: delay.remindAt(from: at))
        waits = ExportWaits.adding(wait, to: waits)
        persist()
        guard await scheduler.requestPermission() else { return false }
        await scheduler.schedule(wait)
        return true
    }

    /// ✕, or a sniff of that vendor's export in that bank (`IntakeRouter.onVendorSniffed`).
    /// Most sniffs clear nothing, so a no-op never writes or wakes an observer.
    func clear(vendor: String, bank: String) {
        let matching = waits.filter { $0.vendor == vendor && $0.bank == bank }
        guard !matching.isEmpty else { return }
        for w in matching { scheduler.cancel(w) }
        waits = ExportWaits.clearing(vendor: vendor, bank: bank, in: waits)
        persist()
    }

    func remove(_ wait: ExportWait) { clear(vendor: wait.vendor, bank: wait.bank) }

    private func persist() {
        defaults.set(try? JSONEncoder().encode(waits), forKey: ExportWaits.defaultsKey)
        onChange?()
    }

    private func persistHabits() {
        defaults.set(try? JSONEncoder().encode(habits), forKey: ExportWaits.habitsKey)
    }
}
