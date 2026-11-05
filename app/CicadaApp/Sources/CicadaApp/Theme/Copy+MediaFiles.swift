import Foundation

/// Meaning index 2 — the words for a recording or video the person adds to search (`MediaFileIndexer`). DR-59:
/// sentence case, plain verbs. Provider-neutral (owner 2026-09-30): the step is described ("on this Mac"), never a
/// framework's or a model's name. One toast per drop, the existing toast — no new visual pattern.
extension Copy {
    static func mediaAddingPhotos(_ n: Int) -> String {
        n == 1 ? "Adding the photo to search…" : "Adding \(n) photos to search…"
    }

    static func mediaAdding(_ n: Int) -> String {
        n == 1 ? "Reading the recording on this Mac so you can search what it says…"
            : "Reading \(n) recordings on this Mac so you can search what they say…"
    }

    static func mediaAdded(_ outcomes: [MediaFileIndexer.AddOutcome]) -> String {
        let photos = outcomes.filter { $0 == .addedPhoto }.count
        if photos > 0, photos == outcomes.count { return photos == 1 ? "Added to search." : "\(photos) added to search." }
        let added = outcomes.filter { if case .added = $0 { return true }; return false }.count
        let words = outcomes.compactMap { o -> String? in if case .noWords(let r) = o { return r }; return nil }
        if added == 0, let reason = words.first { return reason }
        if outcomes.contains(.failed) && added == 0 { return "That recording couldn't be read." }
        let base = added == 1 ? "Added to search. Its words are the recording's, not yours."
            : "\(added) added to search. Their words are the recordings', not yours."
        return words.isEmpty ? base : base + " " + (words.first ?? "")
    }

    static let mediaSpeechDenied =
        "Kept without its words: speech recognition is off for Cicada (System Settings → Privacy & Security → Speech Recognition)."
    static let mediaNoSpeechModel =
        "Kept without its words: this Mac has no speech model for your language yet (turn on Dictation in System Settings → Keyboard)."
    static let mediaNoWords = "Kept without its words: no speech could be read from it on this Mac."

    // MARK: Files in the app (2026-10-29)
    /// File menu — macOS's own title case for a menu item; the twin of dropping a recording on the window.
    static let mediaFileMenuItem = "Add Recording, Video or Photo…"
    static let mediaPickerMessage = "Choose recordings, videos or photos to add to search. They're read on this Mac."
    /// A frame row's detail line in the find palette.
    static let findFrameDetail = "a frame of a video you added"
    static let findPhotoDetail = "a photo you added"
    // MARK: The viewer (ROR-117) — DR-59: a sentence at most, plain verbs.
    static let mediaFilesTitle = "Added files"
    static let mediaListEmpty = "Nothing added yet."
    static let mediaAdd = "Add…"
    static let mediaFilesMenuItem = "Added Files…"
    static let mediaGone = "That file isn't on this Mac."
    static let mediaChooseIt = "Choose it…"
    static let mediaNotTheFile = "That isn't the same file."
    static let mediaOpenDefault = "Open in default app"
    static let mediaShowInFinder = "Show in Finder"
    static let mediaBack = "Back to added files"
    static let mediaClose = "Close"
    static let mediaPlay = "Play"
    static let mediaPause = "Pause"
    static let mediaPosition = "Position"
    static let mediaZoomIn = "Zoom in"
    static let mediaZoomOut = "Zoom out"
    static let mediaOpenPage = "Open page"
    // MARK: A recording's page (ROR-117) — the player, the facts, then the words.
    static let mediaWordsTitle = "The recording's words"
    static let mediaKindRecording = "Recording"
    static let mediaKindVideo = "Video"
    static let mediaKindPhoto = "Photo"
    static let mediaFileMoved = "Cicada doesn't know where that file is now. Add it again to open it from here."
}
