import Foundation

/// Shared across `InboxFocusCard` and its variants — each trims user-typed
/// free text before deciding whether it's empty / before sending it.
extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
