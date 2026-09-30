import Foundation

/// Sleep page v5 — what every door that is not the Sleep page says (the new rule, owner 2026-09-30): each one
/// starts the same run over everything waiting, and while a run is paused each one points to the Sleep page,
/// where the reason for the pause and Continue are. Pure, so the menu bar's words and the intake card's caption
/// are unit tests (`SleepV5DoorsTests`).
struct SleepDoor: Equatable {
    /// `(filed, frozen)` of the paused run, `nil` when nothing is paused.
    var paused: (filed: Int, frozen: Int)?
    /// What a Consolidate would read now (waiting minus parked, M7); `nil` when unknown.
    var readable: Int?
    /// How often a run saves, from the reading options or the status; `nil` while neither has loaded (never a guess).
    var batchSize: Int?
    var running: Bool = false
    /// A run is paused but its record (`filed`/`frozen`) has not loaded yet — the header then says only "Paused",
    /// never "0 of 0".
    var pausedCountsUnknown: Bool = false

    static func == (a: SleepDoor, b: SleepDoor) -> Bool {
        a.paused?.filed == b.paused?.filed && a.paused?.frozen == b.paused?.frozen && (a.paused == nil) == (b.paused == nil)
            && a.readable == b.readable && a.batchSize == b.batchSize && a.running == b.running
            && a.pausedCountsUnknown == b.pausedCountsUnknown
    }

    var isPaused: Bool { paused != nil || pausedCountsUnknown }

    /// The menu-bar worm's action item: never a Continue — it opens the Sleep page while paused.
    var menuItemTitle: String {
        if isPaused { return Copy.SleepV5.continueOnSleepPage }
        return Copy.SleepV5.consolidateAll(readable ?? 0)
    }

    /// The menu's header line while paused ("Paused — 98 of 287 filed"); `nil` otherwise (the worm's own words stay).
    var menuHeader: String? {
        if let paused { return Copy.SleepV5.pausedMenuTitle(filed: paused.filed, frozen: paused.frozen) }
        return pausedCountsUnknown ? Copy.SleepV5.pausedMenuPlain : nil
    }

    /// The caption beside an intake card's or Home's *Read now*: what the click reads, or where to continue.
    var readNowCaption: String? {
        if isPaused { return Copy.SleepV5.pausedDoorCaption }
        guard let readable, readable > 0 else { return nil }
        return Copy.SleepV5.readNowCaption(waiting: readable, batchSize: batchSize)
    }
}
