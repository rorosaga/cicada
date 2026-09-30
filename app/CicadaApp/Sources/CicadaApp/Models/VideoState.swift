import Foundation

// G162 — the honest state of every saved video and the person's video queue, as `GET /videos/state` and
// `GET /videos/summary` serve them. Every type decodes leniently (an older or newer backend never drops a row: an
// unknown value reads as nil, or as `.unknown` for the derived state). The server is the ONLY deriver of a state
// (spec P13): the episode facts are not on the wire, so there is no Swift twin of the union rule — the app decodes and
// labels.

/// Decodes a closed wire enum; a value this build does not know reads as nil rather than failing the row.
private func lenient<E: RawRepresentable>(_ c: KeyedDecodingContainer<VideoStateItem.CodingKeys>, _ key: VideoStateItem.CodingKeys,
                                          as _: E.Type) -> E? where E.RawValue == String {
    guard let raw = try? c.decodeIfPresent(String.self, forKey: key) else { return nil }
    return E(rawValue: raw)
}

/// What Cicada holds for one video: nothing but its metadata, a transcript, frames (a watch), both, or a record made
/// before Cicada asked how it was read.
enum VideoWatchState: String, Equatable, Sendable, CaseIterable {
    case none, transcript, watched
    case watchedAndTranscript = "watched_and_transcript"
    case recorded
    /// A state a newer backend invented; drawn as no state at all.
    case unknown

    init(wire: String?) { self = VideoWatchState(rawValue: wire ?? "") ?? .unknown }
}

/// What the person asked for. A watch implies a transcript.
enum VideoWant: String, Equatable, Sendable, CaseIterable { case transcript, watch }

enum VideoQueueState: String, Equatable, Sendable { case queued, claimed, failed }

/// Why an agent handed a video back. `needsLogin` is the one that needs the person.
enum VideoFailCode: String, Equatable, Sendable {
    case needsLogin = "needs_login"
    case noCaptions = "no_captions"
    case notFound = "not_found"
    case blocked, failed
}

/// How faithful a record's words are: `verbatim` (captions) or `approximate` (a model's reading of the link, or a
/// record that never said).
enum VideoFidelity: String, Equatable, Sendable { case verbatim, approximate }

/// What an agent said it used — self-reported, never verified (R-VU2).
enum VideoBasis: String, Equatable, Sendable { case transcript, frames, both }

/// How an agent said it read the video; a closed set on the server (`video_state.ENGINES`).
enum VideoEngine: String, Equatable, Sendable {
    case captions
    case videoLink = "video_link"
    case localFrames = "local_frames"
    case speechToText = "speech_to_text"
    case browser, other
}

/// The run card's *How* choice (P7): the wire words are `auto`, `captions`, `link`.
enum VideoMethod: String, Equatable, Sendable, CaseIterable { case auto, captions, link }

/// One saved video's line in `GET /videos/state`. Title, channel, thumbnail, length and site are NOT repeated: the app
/// joins by `mediaEntityId|url` to the `MediaFeedItem` it already holds (`id` is that same join key).
struct VideoStateItem: Decodable, Equatable, Identifiable, Sendable {
    /// The url-index key — what every write and the hand-off name.
    var key: String
    var mediaEntityId: String
    var url: String
    var state: VideoWatchState
    var want: VideoWant?
    var queueState: VideoQueueState?
    var claimedBy: String?
    var attempts: Int?
    var failedCode: VideoFailCode?
    var failedReason: String?
    var batch: String?
    var basis: VideoBasis?
    var engine: VideoEngine?
    var fidelity: VideoFidelity?
    var episodeId: String?
    var recordedAt: String?
    var recordedBy: String?
    /// True only for a record Sleep consolidated, false when Sleep has not read it yet, and nil when an agent flipped
    /// the flag itself (unknowable — the line says nothing then).
    var readBySleep: Bool?

    /// The Feed's own row id (`MediaFeedItem.id`).
    var id: String { mediaEntityId + "|" + url }

    enum CodingKeys: String, CodingKey {
        case key, mediaEntityId, url, state, want, queueState, claimedBy, attempts, failedCode, failedReason, batch
        case basis, engine, fidelity, episodeId, recordedAt, recordedBy, readBySleep
    }

    init(key: String, mediaEntityId: String, url: String, state: VideoWatchState = .none, want: VideoWant? = nil,
         queueState: VideoQueueState? = nil, claimedBy: String? = nil, attempts: Int? = nil,
         failedCode: VideoFailCode? = nil, failedReason: String? = nil, batch: String? = nil, basis: VideoBasis? = nil,
         engine: VideoEngine? = nil, fidelity: VideoFidelity? = nil, episodeId: String? = nil,
         recordedAt: String? = nil, recordedBy: String? = nil, readBySleep: Bool? = nil) {
        self.key = key
        self.mediaEntityId = mediaEntityId
        self.url = url
        self.state = state
        self.want = want
        self.queueState = queueState
        self.claimedBy = claimedBy
        self.attempts = attempts
        self.failedCode = failedCode
        self.failedReason = failedReason
        self.batch = batch
        self.basis = basis
        self.engine = engine
        self.fidelity = fidelity
        self.episodeId = episodeId
        self.recordedAt = recordedAt
        self.recordedBy = recordedBy
        self.readBySleep = readBySleep
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        mediaEntityId = (try? c.decode(String.self, forKey: .mediaEntityId)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
        state = VideoWatchState(wire: try? c.decodeIfPresent(String.self, forKey: .state))
        want = lenient(c, .want, as: VideoWant.self)
        queueState = lenient(c, .queueState, as: VideoQueueState.self)
        claimedBy = (try? c.decodeIfPresent(String.self, forKey: .claimedBy)) ?? nil
        attempts = (try? c.decodeIfPresent(Int.self, forKey: .attempts)) ?? nil
        failedCode = lenient(c, .failedCode, as: VideoFailCode.self)
        failedReason = (try? c.decodeIfPresent(String.self, forKey: .failedReason)) ?? nil
        batch = (try? c.decodeIfPresent(String.self, forKey: .batch)) ?? nil
        basis = lenient(c, .basis, as: VideoBasis.self)
        engine = lenient(c, .engine, as: VideoEngine.self)
        fidelity = lenient(c, .fidelity, as: VideoFidelity.self)
        episodeId = (try? c.decodeIfPresent(String.self, forKey: .episodeId)) ?? nil
        recordedAt = (try? c.decodeIfPresent(String.self, forKey: .recordedAt)) ?? nil
        recordedBy = (try? c.decodeIfPresent(String.self, forKey: .recordedBy)) ?? nil
        readBySleep = (try? c.decodeIfPresent(Bool.self, forKey: .readBySleep)) ?? nil
    }

    /// True while the video is in the person's queue in any state.
    var isQueued: Bool { queueState != nil }
}

/// The active hand-off's progress. `done` is the numerator and only moves when a record lands (never on "picked up").
struct VideoBatch: Decodable, Equatable, Sendable {
    var id: String
    var createdAt: String?
    var method: VideoMethod
    var total: Int
    var done: Int
    var claimed: Int
    var waiting: Int
    var failed: Int
    var keys: [String]

    enum CodingKeys: String, CodingKey { case id, createdAt, method, total, done, claimed, waiting, failed, keys }

    init(id: String, createdAt: String? = nil, method: VideoMethod = .auto, total: Int, done: Int = 0, claimed: Int = 0,
         waiting: Int = 0, failed: Int = 0, keys: [String] = []) {
        self.id = id
        self.createdAt = createdAt
        self.method = method
        self.total = total
        self.done = done
        self.claimed = claimed
        self.waiting = waiting
        self.failed = failed
        self.keys = keys
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? ""
        createdAt = (try? c.decodeIfPresent(String.self, forKey: .createdAt)) ?? nil
        method = VideoMethod(rawValue: (try? c.decodeIfPresent(String.self, forKey: .method)) ?? "") ?? .auto
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        done = (try? c.decode(Int.self, forKey: .done)) ?? 0
        claimed = (try? c.decode(Int.self, forKey: .claimed)) ?? 0
        waiting = (try? c.decode(Int.self, forKey: .waiting)) ?? 0
        failed = (try? c.decode(Int.self, forKey: .failed)) ?? 0
        keys = (try? c.decode([String].self, forKey: .keys)) ?? []
    }
}

/// `GET /videos/summary` and the `queue` block of `GET /videos/state` — one function on the server, so they cannot
/// disagree. The picker's three tabs are disjoint and sum to `total`: Not yet read = `unread`, Queued = `queued +
/// claimed + failed`, Read = `read`.
struct VideoSummary: Decodable, Equatable, Sendable {
    var total = 0
    var unread = 0
    var queued = 0
    var claimed = 0
    var failed = 0
    var read = 0
    var batch: VideoBatch?
    /// The earliest instant a lease or an expiry comes due (ISO) — the app revalidates there, since a lapse writes
    /// nothing and would otherwise leave "Picked up" on screen (H2).
    var nextChangeAt: String?

    enum CodingKeys: String, CodingKey { case total, unread, queued, claimed, failed, read, batch, nextChangeAt }

    init(total: Int = 0, unread: Int = 0, queued: Int = 0, claimed: Int = 0, failed: Int = 0, read: Int = 0,
         batch: VideoBatch? = nil, nextChangeAt: String? = nil) {
        self.total = total
        self.unread = unread
        self.queued = queued
        self.claimed = claimed
        self.failed = failed
        self.read = read
        self.batch = batch
        self.nextChangeAt = nextChangeAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        unread = (try? c.decode(Int.self, forKey: .unread)) ?? 0
        queued = (try? c.decode(Int.self, forKey: .queued)) ?? 0
        claimed = (try? c.decode(Int.self, forKey: .claimed)) ?? 0
        failed = (try? c.decode(Int.self, forKey: .failed)) ?? 0
        read = (try? c.decode(Int.self, forKey: .read)) ?? 0
        batch = (try? c.decodeIfPresent(VideoBatch.self, forKey: .batch)) ?? nil
        nextChangeAt = (try? c.decodeIfPresent(String.self, forKey: .nextChangeAt)) ?? nil
    }

    /// Everything the person has put in the queue and not yet had recorded: the picker's Queued tab.
    var inQueue: Int { queued + claimed + failed }
}

struct VideosStateResponse: Decodable, Equatable, Sendable {
    var items: [VideoStateItem]
    var queue: VideoSummary
    var nextChangeAt: String?
    var shape: String?

    enum CodingKeys: String, CodingKey { case items, queue, nextChangeAt, shape }

    init(items: [VideoStateItem] = [], queue: VideoSummary = VideoSummary(), nextChangeAt: String? = nil,
         shape: String? = nil) {
        self.items = items
        self.queue = queue
        self.nextChangeAt = nextChangeAt
        self.shape = shape
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // A row that cannot decode drops alone; the rest of the list stands.
        var rows: [VideoStateItem] = []
        if var list = try? c.nestedUnkeyedContainer(forKey: .items) {
            while !list.isAtEnd {
                if let row = try? list.decode(VideoStateItem.self) { rows.append(row) } else { _ = try? list.decode(Skip.self) }
            }
        }
        items = rows
        queue = (try? c.decode(VideoSummary.self, forKey: .queue)) ?? VideoSummary()
        nextChangeAt = (try? c.decodeIfPresent(String.self, forKey: .nextChangeAt)) ?? nil
        shape = (try? c.decodeIfPresent(String.self, forKey: .shape)) ?? nil
        if queue.nextChangeAt == nil { queue.nextChangeAt = nextChangeAt }
    }

    private struct Skip: Decodable { init(from decoder: Decoder) throws {} }
}

/// What `POST /videos/run/handoff` answers: the batch it stamped and the prompt to copy.
struct VideoHandoffResponse: Decodable, Equatable, Sendable {
    var batch: VideoBatch
    var prompt: String
}

struct VideoPromptResponse: Decodable, Equatable, Sendable { var prompt: String }
