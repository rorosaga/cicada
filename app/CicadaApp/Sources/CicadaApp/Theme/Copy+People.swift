import Foundation

/// G146 — the words pictures, Clusters' cards and the person card add, in their own file for the reason
/// `Copy+Inbox.swift` gives: parallel tracks edit `Copy.swift`. DR-59: sentence case, plain verbs, no ids (DR-54).
extension Copy {
    enum People {
        /// C11 — where a picture came from: every picture's hover and the card's source line (F-12).
        static func sourceLine(_ source: PictureSource?) -> String {
            switch source {
            case .upload: "Picture you added"
            case .initials: "Initials — your choice"
            case .contacts: "Photo from your Contacts"
            case .logo: "Logo from its website"
            case .thumbnail: "Preview from the saved page"
            case nil: "No picture yet"
            }
        }
    }
}
