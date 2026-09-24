import Foundation
import Observation

/// Backs `EngineChooser` (G122) and, since DS-3b, the Sleep page's quick engine menu — one object,
/// one source of truth (R-HS7). Ruling 6: `/sleep/engine` has no `Store`
/// domain, no ETag, and is never SSE-pushed — the same shape as
/// `ScheduleConfig`/`SleepViewModel.updateSchedule`, which already gets by
/// with a plain `APIClient` round trip and no optimistic-apply/rollback
/// `Mutation`. Copying that pattern here (rather than inventing a
/// `SetSleepEngine` `Mutation`) means one settings value with one model
/// watching it — the server's echoed response is
/// simply assigned back, since it is authoritative by construction
/// (`sleep_engine_prefs.build_response` re-reads through the same function
/// after a PUT, so it can never drift from what a subsequent GET would say).
///
/// Injectable (`fetch`/`update`, the same shape as `SleepViewModel`'s `fetch…` closures) so
/// `EngineQuickMenuTests` drives it with synthetic bodies and never reaches `APIClient.shared`.
/// `writeFailed` is the quick menu's "nothing changed" line; a success clears `errorMessage`,
/// which the pre-DS-3b model never did (`LiveSetupEffects.saveEngine` still clears it first and
/// reads it after, unchanged).
@Observable
@MainActor
final class SleepEngineViewModel {
    typealias Fetch = () async throws -> SleepEngineResponse
    typealias Update = (_ mode: String, _ model: String?, _ disambiguationModel: String?,
                        _ allowOverage: Bool?) async throws -> SleepEngineResponse

    var response: SleepEngineResponse?
    var errorMessage: String?
    /// A write is on the wire: the quick menu's rows wait, so two taps never race (R-HS7).
    private(set) var isSaving = false
    /// The last write failed and nothing changed — said in words, never a silent revert.
    private(set) var writeFailed = false

    private let fetch: Fetch
    private let update: Update

    init(fetch: @escaping Fetch = { try await APIClient.shared.fetchSleepEngine() },
         update: @escaping Update = { mode, model, disambiguation, overage in
             try await APIClient.shared.updateSleepEngine(mode: mode, model: model,
                                                           disambiguationModel: disambiguation,
                                                           allowOverage: overage)
         }) {
        self.fetch = fetch
        self.update = update
    }

    func load() async {
        do {
            response = try await fetch()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// `allowOverage` (R-E13) defaults to nil — "leave the stored opt-in
    /// alone" — so a mode or model change never touches it by accident.
    func set(mode: String, model: String?, disambiguationModel: String?, allowOverage: Bool? = nil) async {
        isSaving = true
        defer { isSaving = false }
        do {
            response = try await update(mode, model, disambiguationModel, allowOverage)
            errorMessage = nil
            writeFailed = false
        } catch {
            errorMessage = error.localizedDescription
            writeFailed = true
        }
    }

    /// R-HS7 — the one door both surfaces write through.
    func apply(_ write: EngineWrite) async {
        await set(mode: write.mode, model: write.model, disambiguationModel: nil)
    }
}
