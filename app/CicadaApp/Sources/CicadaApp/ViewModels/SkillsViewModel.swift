import Foundation

/// Settings → Skills' data (G138) — fetched when the Settings window opens and
/// after an install. Owned by `SettingsScene` so search can index the entries
/// too. Not a Store domain: install state is derived per request (R-O23).
@Observable
@MainActor
final class SkillsViewModel {
    private(set) var response: RecommendedSkillsResponse?
    private(set) var problem: String?

    var shown: [RecommendedSkill] { response.map(Self.shown(from:)) ?? [] }
    var installedHere: [RecommendedSkill] { response?.installed ?? [] }
    var all: [RecommendedSkill] { shown + installedHere }

    /// The budget rule (R5 §3): never more than five at once, whatever arrives.
    nonisolated static func shown(from response: RecommendedSkillsResponse) -> [RecommendedSkill] {
        Array(response.recommended.prefix(min(response.maxShown, 5)))
    }

    func load() async {
        do {
            response = try await APIClient.shared.fetchRecommendedSkills()
            problem = nil
        } catch {
            problem = "Couldn't reach Cicada's backend."
        }
    }
}
