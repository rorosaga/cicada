import Foundation

/// G146 — the words pictures, Clusters' cards and the person card add, in their own file for the reason
/// `Copy+Inbox.swift` gives: parallel tracks edit `Copy.swift`. DR-59: sentence case, plain verbs, no ids (DR-54).
extension Copy {
    enum People {
        static let changePicture = "Change picture…"
        static let addPicture = "Add a picture…"
        static let change = "Change…"
        static let useInitials = "Use initials instead"
        static let removePicture = "Remove picture"
        static let pickPrompt = "Use picture"
        static let saveFailed = "Couldn't save the picture — try again."
        static let sleepBusy = "Sleep is updating your memory — try the picture again in a moment."
        static let backendDown = "Cicada's engine isn't running, so the picture wasn't saved."

        static func useDetected(_ source: PictureSource) -> String {
            switch source {
            case .contacts: "Use the photo from Contacts"
            case .logo: "Use the logo"
            case .thumbnail: "Use the saved preview"
            case .upload, .initials: "Use the picture Cicada found"
            }
        }

        static func optionLabel(_ option: PictureMenuModel.Option) -> String {
            switch option {
            case .change: changePicture
            case .add: addPicture
            case .useInitials: useInitials
            case .remove: removePicture
            case .useDetected(let source): useDetected(source)
            }
        }

        static func changeHelp(_ name: String) -> String { "Change the picture for \(name) — or drop one here" }
        static func pickMessage(_ name: String) -> String {
            "Choose a picture for \(name). Cicada keeps a small copy in your memory."
        }

        static func importFailed(_ failure: PictureImport.Failure) -> String {
            switch failure {
            case .unreadable: "That file isn't a picture Cicada can read."
            case .tooSmall: "That picture is too small to show."
            case .tooLarge: "That picture is still too large after shrinking it."
            }
        }

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
