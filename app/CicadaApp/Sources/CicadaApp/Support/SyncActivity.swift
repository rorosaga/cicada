import Foundation
import Observation

/// Round 4 (T-Sources, R-SR17) — the one place a row learns that its source is syncing right now, how far along it is,
/// and whether it can be stopped. Each reader that owns a cancellable run (`BrowserWatcher`, `TabGroupWatcher`,
/// `ContactsReader`) reports into it; `SourceRow` reads it on Sources, in Integrations and on Home. Owner decision
/// 2026-09-24: "start syncing as soon as connected … do give an x button to cancel sync right there."
///
/// **× stops the run, never the consent (R-SR11).** `cancel` calls the reader's own closure, which cancels its task;
/// whatever the backend already finished stays, and the reader records no signature, so the next change reads again.
@MainActor
@Observable
final class SyncActivity {
    struct Run: Equatable {
        var detail: String? = nil
        /// 0…1 when the reader knows how far it is; nil draws no meter (never a guessed number).
        var fraction: Double? = nil
        var cancellable: Bool
    }

    private(set) var runs: [String: Run] = [:]
    @ObservationIgnored private var cancels: [String: @MainActor () -> Void] = [:]

    func run(for channel: String) -> Run? { runs[channel] }

    func began(_ channel: String, detail: String? = nil, cancel: (@MainActor () -> Void)?) {
        runs[channel] = Run(detail: detail, fraction: nil, cancellable: cancel != nil)
        cancels[channel] = cancel
    }

    func progressed(_ channel: String, detail: String?, fraction: Double? = nil) {
        guard runs[channel] != nil else { return }
        runs[channel]?.detail = detail
        runs[channel]?.fraction = fraction.map { min(max($0, 0), 1) }
    }

    func ended(_ channel: String) {
        runs[channel] = nil
        cancels[channel] = nil
    }

    /// Calls the reader's closure at most once, then clears the run so the row stops showing the × at once.
    func cancel(_ channel: String) {
        let cancel = cancels[channel]
        ended(channel)
        cancel?()
    }
}

/// What counts as the person stopping a run rather than a failure: a Swift cancellation, or URLSession's own.
enum SyncCancellation {
    static func isCancellation(_ error: Error) -> Bool {
        if error is CancellationError { return true }
        if let url = error as? URLError { return url.code == .cancelled }
        let ns = error as NSError
        return ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled
    }
}
