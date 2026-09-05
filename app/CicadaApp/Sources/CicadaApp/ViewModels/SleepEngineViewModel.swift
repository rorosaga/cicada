import Foundation
import Observation

/// Backs `EngineCard` (G122). Ruling 6: `/sleep/engine` has no `Store`
/// domain, no ETag, and is never SSE-pushed — the same shape as
/// `ScheduleConfig`/`SleepViewModel.updateSchedule`, which already gets by
/// with a plain `APIClient` round trip and no optimistic-apply/rollback
/// `Mutation`. Copying that pattern here (rather than inventing a
/// `SetSleepEngine` `Mutation`) means one settings page owns one settings
/// value with nothing else watching it — the server's echoed response is
/// simply assigned back, since it is authoritative by construction
/// (`sleep_engine_prefs.build_response` re-reads through the same function
/// after a PUT, so it can never drift from what a subsequent GET would say).
@Observable
@MainActor
final class SleepEngineViewModel {
    var response: SleepEngineResponse?
    var errorMessage: String?

    func load() async {
        do {
            response = try await APIClient.shared.fetchSleepEngine()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func set(mode: String, model: String?, disambiguationModel: String?) async {
        do {
            response = try await APIClient.shared.updateSleepEngine(
                mode: mode, model: model, disambiguationModel: disambiguationModel
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
