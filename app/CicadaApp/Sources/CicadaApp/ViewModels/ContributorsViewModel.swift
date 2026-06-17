import Foundation
import Observation

// M3 (backlog A2): repo-wide model/user attribution.
// NOT BUILD-VERIFIED — needs Rodrigo to compile in Xcode.
@Observable
@MainActor
final class ContributorsViewModel {
    var contributors: [Contributor] = []
    var isLoading = false
    var errorMessage: String?

    var totalCommits: Int { contributors.reduce(0) { $0 + $1.commitCount } }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        errorMessage = nil
        do {
            contributors = try await APIClient.shared.fetchContributors()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
