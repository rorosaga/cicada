import Foundation

/// G61 "Where to check" on the entity card, and the fade explainer that replaced Settings' Memory page.
extension Copy {
    enum WhereChips {
        static let label = "Where to check"
        static let add = "Add a place to check"
        static let addShort = "Add"
        static let addPrompt = "Paste a link"
        static let remove = "Remove"
        static func open(_ label: String) -> String { "Open \(label)" }
        static let fadeHelp = "How pages fade"
        static let fadeTitle = "How pages fade"
        static let fadeBody = """
        A page fades when nothing mentions it, counted from when it was last said. Mentioning it again brings it back. \
        A faded page is archived, never deleted. Things that don't go out of date never fade.
        """
    }
}
