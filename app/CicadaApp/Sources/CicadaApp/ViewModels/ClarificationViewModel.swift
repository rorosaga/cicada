import Foundation

@Observable
final class ClarificationViewModel {
    var clarifications: [Clarification] = []
    var isLoading = false
    var errorMessage: String?

    var pendingCount: Int { clarifications.count }

    func loadClarifications() async {
        isLoading = true
        do {
            clarifications = try await APIClient.shared.fetchClarifications()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    func resolveClarification(id: String, action: String, answer: String? = nil, mergeTarget: String? = nil) async {
        do {
            try await APIClient.shared.resolveClarification(id: id, action: action, answer: answer, mergeTarget: mergeTarget)
            clarifications.removeAll { $0.id == id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
