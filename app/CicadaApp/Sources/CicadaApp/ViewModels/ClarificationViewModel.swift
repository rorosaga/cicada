import Foundation

@Observable
final class ClarificationViewModel {
    var clarifications: [Clarification] = MockData.clarifications

    var pendingCount: Int { clarifications.count }

    func resolveClarification(id: String) {
        clarifications.removeAll { $0.id == id }
    }
}
