import Foundation

/// ROR-117 / G43 — what the in-app viewer shows for an added file. Pure: no player and no view, so every rule is a
/// plain XCTest (the `VideoPlayerModel` grammar). The file is the one this Mac last saw (`MediaFilePlaces`, the app's
/// own record — the backend never has a path, G195) and the video rail holds (G162): a file already here is played,
/// nothing is downloaded and no stream is derived.
enum MediaViewerModel {
    enum Target: Equatable {
        /// A recording or video, started at the second the hit matched (0 when it names none).
        case play(url: URL, kind: MediaKind, start: Double)
        case photo(url: URL)
        /// Moved, deleted, or never on this Mac (a memo known from another device): said in a sentence, never a dead
        /// player.
        case missing
    }

    static func target(id: String, at: Double?, places: MediaFilePlaces) -> Target {
        guard let url = places.url(of: id), let kind = MediaKind.of(url) else { return .missing }
        switch kind {
        case .image: return .photo(url: url)
        case .audio, .video: return .play(url: url, kind: kind, start: start(at))
        }
    }

    /// The second to start at: the hit's, never negative, never a non-number.
    static func start(_ at: Double?) -> Double {
        guard let at, at.isFinite, at > 0 else { return 0 }
        return at
    }

    /// The surface opens: jump to the matched second, then play (a hit is a request to hear it).
    static func begin(_ controller: VideoPlaybackController, at start: Double) {
        controller.seek(to: start)
        controller.play()
    }

    /// The surface closes: stop and let go, so nothing keeps playing or holding the file.
    static func end(_ controller: VideoPlaybackController?) {
        controller?.stop()
    }

    /// `m:ss`, or `h:mm:ss` from an hour (the clock the search hit's subtitle shows).
    static func clock(_ seconds: Double) -> String {
        let total = seconds.isFinite ? max(0, Int(seconds)) : 0
        let h = total / 3600, m = total % 3600 / 60, s = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }

    /// Whether `url` is the file added under `id`. An ordinary added file's id is the front of its sha256
    /// (`media_files.file_id_for`), so a file chosen to replace a moved one must hash to it; a store's own item
    /// (a Voice Memo, keyed by the store) cannot be re-pointed by hand, so it is refused here.
    static func isTheFile(_ url: URL, id: String, source: String?) -> Bool {
        guard source == nil, let sha = MediaFileIndexer.sha256(of: url) else { return false }
        return String(sha.prefix(16)) == id
    }
}

/// Where the viewer sheet is: the list of added files, or one file (with where to start in it).
enum MediaRoute: Equatable, Identifiable {
    case list
    case file(id: String, at: Double?)

    var id: String {
        switch self {
        case .list: "list"
        case .file(let id, _): "file:\(id)"
        }
    }
}

/// `GET /files` — an added file's description (never its words, never a path).
struct AddedFile: Decodable, Equatable, Identifiable {
    let id: String
    let name: String
    let kind: String
    let durationS: Double?
    let addedAt: String?
    let recordedAt: String?
    /// A store that names its own items (`voice_memos`); nil for a file the person picked or dropped.
    let source: String?
    /// The file's page in memory (`media_pages`), once it has one.
    let page: String?

    enum CodingKeys: String, CodingKey {
        case id, name, kind, source, page
        case durationS = "duration_s", addedAt = "added_at", recordedAt = "recorded_at"
    }

    var glyph: String {
        switch kind {
        case "video": "film"
        case "image": "photo"
        default: "waveform"
        }
    }

    /// The list's one line under the name: how long it is (a photo has no length).
    var detail: String? { durationS.map(MediaViewerModel.clock) }
}

struct AddedFilesResponse: Decodable { let files: [AddedFile] }
