import Foundation

@Observable
final class NudgeViewModel {
    var nudges: [Nudge] = MockData.nudges

    var pendingCount: Int { nudges.count }

    func resolveNudge(id: String) {
        nudges.removeAll { $0.id == id }
    }
}
