import AVFoundation
import Foundation

/// Chat images (2026-11-04) — a video's or a voice message's length, read from the file the chat app holds on this
/// Mac, for its tile. The one AVFoundation call of the chat panel, kept in its own file (`AVImportLintTests`): it
/// loads only the asset's duration, never plays, decodes or copies anything.
enum ChatMediaDuration {
    static func seconds(_ url: URL) async -> Double? {
        let asset = AVURLAsset(url: url)
        guard let time = try? await asset.load(.duration) else { return nil }
        let seconds = CMTimeGetSeconds(time)
        return seconds.isFinite && seconds > 0 ? seconds : nil
    }
}
