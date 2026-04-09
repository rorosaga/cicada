import Foundation

@Observable
final class NudgeViewModel {
    var nudges: [Nudge] = []
    var isLoading = false
    var errorMessage: String?

    var pendingCount: Int { nudges.count }

    func loadNudges() async {
        isLoading = true
        do {
            nudges = try await APIClient.shared.fetchNudges()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func resolveNudge(id: String, action: String, answer: String? = nil) async {
        do {
            try await APIClient.shared.resolveNudge(id: id, action: action, answer: answer)
            nudges.removeAll { $0.id == id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
