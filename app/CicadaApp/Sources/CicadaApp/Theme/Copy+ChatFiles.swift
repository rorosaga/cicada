import Foundation

extension Copy {
    /// Chat images (2026-11-04) — the words of an attachment's tile in a chat.
    enum ChatFiles {
        static let notOnMac = "Not on this Mac"
        static let openHelp = "Open in Quick Look"
        static let voiceMessage = "Voice message"

        /// The kind word a tile says beside the name: "Image", "Video", "Voice message" (an audio file with no name
        /// of its own), "File".
        static func kind(_ kind: String, name: String) -> String {
            if kind == "audio", name == "unnamed" || name.isEmpty { return voiceMessage }
            return Copy.Provenance.attachmentKind(kind, generated: false)
        }

        /// What VoiceOver says for a tile: its kind, its name, its length and whether it is on this Mac.
        static func spoken(kind: String, name: String, length: String?, onMac: Bool) -> String {
            var parts = [Self.kind(kind, name: name)]
            if name != "unnamed", !name.isEmpty { parts.append(name) }
            if let length { parts.append(length) }
            if !onMac { parts.append(notOnMac) }
            return parts.joined(separator: ", ")
        }
    }
}
