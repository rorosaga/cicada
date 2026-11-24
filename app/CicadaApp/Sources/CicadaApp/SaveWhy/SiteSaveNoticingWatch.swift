import Foundation
import Observation
import OSLog

/// G221 (ruling 77) — keeps the save watcher's view of "which sites are noticed" current. A site is noticed when its
/// source is set up (`SiteSaveNoticing`), and that word is the Sources catalogue's: it changes when a list is turned on from
/// the page, the card, an agent's settings or the notch, and when the catalogue first loads after launch. This reads the
/// set under Observation, so the watcher is told the moment any of that moves, whoever moved it, and logs the change (ids
/// only, never a page). A switch on the Sources page tells the watcher itself (`SiteSaveSwitches.changed`).
@MainActor
final class SiteSaveNoticingWatch {
    static let logger = Logger(subsystem: "com.cicada.app", category: "site-saves")

    /// The site keys noticed now (`SiteSavePrefs.noticed`). Read inside the tracking, so what it touches is watched.
    var read: () -> Set<String> = { [] }
    /// The set moved: look again at what is in front.
    var changed: () -> Void = {}

    private(set) var last: Set<String>?
    private var started = false

    func start() {
        guard !started else { return }
        started = true
        observe()
    }

    /// One look at the set, and the next look when anything it read changes. A change is announced after it has landed
    /// (`withObservationTracking` fires before it does).
    private func observe() {
        let now = withObservationTracking(read) { [weak self] in
            Task { @MainActor in self?.observe() }
        }
        settle(now)
    }

    /// Records what is noticed now; tells the watcher only when it differs from the last look.
    func settle(_ now: Set<String>) {
        guard last != now else { return }
        let first = last == nil
        last = now
        Self.logger.info("noticing saves on: \(now.sorted().joined(separator: ","), privacy: .public)")
        // The watcher starts from the same set at launch; only a later move needs telling.
        if !first { changed() }
    }
}
