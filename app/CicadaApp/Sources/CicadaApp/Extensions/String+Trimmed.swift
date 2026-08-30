import Foundation

/// Shared across `InboxCardView` and `QuestionView` — both trim user-typed
/// free text before deciding whether it's empty / before sending it.
extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
