import AppKit
import SwiftUI

// MARK: - Pictures Cicada's own API serves for Sources rows (Sources v4)

/// Where a Sources picture is asked (pure, tested): a Messages chat's photo and a watched YouTube video's still, both
/// from Cicada's own API — the app fetches nothing of the web. The `?v=` is the photo's hash, so a changed photo is a
/// new address and no cache is ever stale.
enum SourcePictures {
    /// A chat id is the app's hash of the chat — hex only, so it can never reshape the path.
    static func chatPhotoPath(_ face: (id: String, photo: String?)) -> String? {
        guard let photo = face.photo, !photo.isEmpty, isHex(face.id), isHex(photo) else { return nil }
        return "/sources/messages/chats/\(face.id)/photo?v=\(photo)"
    }

    /// A YouTube video id (the backend's own pin: letters, digits, `-` and `_`), asked by the day it was watched on
    /// (review of #358: the backend checks the id against that one day's record).
    static func stillPath(episode: String, videoId: String?) -> String? {
        guard let videoId, (6...20).contains(videoId.count), isToken(videoId, extra: "-_"),
              !episode.isEmpty, episode.count <= 80, isToken(episode, extra: "-_.")
        else { return nil }
        return "/sources/watch-history/days/\(episode)/videos/\(videoId)/thumbnail"
    }

    private static func isToken(_ s: String, extra: String) -> Bool {
        s.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || extra.contains($0)) }
    }

    private static func isHex(_ s: String) -> Bool {
        !s.isEmpty && s.count <= 64 && s.allSatisfy { $0.isHexDigit }
    }
}

/// The pictures above, kept in memory per bank and path, misses too (a 404 means "draw the monogram"); a network blip
/// is never remembered as a miss. Never on disk, never a Store domain.
actor SourcePictureStore {
    static let shared = SourcePictureStore()

    typealias Fetcher = @Sendable (String) async throws -> Data?
    private let fetch: Fetcher
    private var images: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private var inFlight: [String: Task<NSImage?, Never>] = [:]
    /// At most this many pictures are asked at once (review of #358); the rest wait their turn, in order.
    static let maxConcurrent = 4
    private var running = 0
    private var waiting: [CheckedContinuation<Void, Never>] = []

    init(fetch: @escaping Fetcher = { try await APIClient.shared.fetchSourcePicture(path: $0) }) { self.fetch = fetch }

    private func acquire() async {
        if running < Self.maxConcurrent { running += 1; return }
        await withCheckedContinuation { waiting.append($0) }
    }

    private func release() {
        if waiting.isEmpty { running -= 1 } else { waiting.removeFirst().resume() }
    }

    /// How many asks run now (tests).
    var inFlightCount: Int { running }

    func image(path: String, bank: String) async -> NSImage? {
        let key = "\(bank)|\(path)"
        if let hit = images[key] { return hit }
        if misses.contains(key) { return nil }
        if let running = inFlight[key] { return await running.value }
        let fetch = self.fetch
        let task = Task<NSImage?, Never> {
            await self.acquire()
            defer { self.release() }
            if Task.isCancelled { return nil }
            do {
                guard let data = try await fetch(path) else { return nil }
                return NSImage(data: data)
            } catch {
                return nil
            }
        }
        inFlight[key] = task
        let answer = await task.value
        inFlight[key] = nil
        if let answer { images[key] = answer } else { misses.insert(key) }
        return answer
    }
}

// MARK: - Faces

/// Sources v4 — the faces on a row, pure: at most three, then "+N" for the rest (owner 2026-10-19).
enum SourceFaceStack {
    static let maxShown = 3

    static func plan(_ faces: [SourceFace], more: Int) -> (shown: [SourceFace], more: Int) {
        let shown = Array(faces.prefix(maxShown))
        return (shown, max(0, more) + max(0, faces.count - shown.count))
    }
}

/// Up to three faces overlapping, newest in front, then a "+N" ring for the rest — the chats that fed Messages, the
/// sites a saved source's things came from. Each face sits on a ring of the page's own ground so the overlap reads
/// without a shadow (DR-9); a chat is a circle (a person's picture), a site its tab-like mark (`SiteIcon`). Decoration
/// beside the row's words, so it is spoken once as a sentence and never a button (DR-38: the row already opens).
struct SourceFaces: View {
    let faces: [SourceFace]
    let more: Int
    var side: CGFloat = 18

    var body: some View {
        let plan = SourceFaceStack.plan(faces, more: more)
        let s = CicadaTheme.scaled(side)
        HStack(spacing: -s * 0.3) {
            ForEach(Array(plan.shown.enumerated()), id: \.element.id) { index, face in
                FaceView(face: face, side: s)
                    .padding(CicadaTheme.scaled(1.5))
                    .background(CicadaTheme.bgBase,
                                in: face.kind == .site ? AnyShape(CicadaTheme.shape(CicadaTheme.scaled(5)))
                                                       : AnyShape(Circle()))
                    .zIndex(Double(plan.shown.count - index))
            }
            if plan.more > 0 {
                Text(Copy.facesMore(plan.more))
                    .font(CicadaTheme.font(size: max(9, side * 0.5), weight: .medium))
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .padding(.horizontal, CicadaTheme.scaled(3))
                    .frame(minWidth: s, minHeight: s)
                    .background(Capsule().strokeBorder(CicadaTheme.border, lineWidth: 1))
                    .padding(CicadaTheme.scaled(1.5))
                    .background(Capsule().fill(CicadaTheme.bgBase))
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.facesSpoken(plan.shown.map(\.label), more: plan.more))
    }
}

/// One face: a chat's photo (or its monogram in a ring), or a site's own mark.
private struct FaceView: View {
    let face: SourceFace
    let side: CGFloat

    var body: some View {
        switch face.kind {
        case .chat, .unknown:
            ChatFace(id: face.id, label: face.label, photo: face.photo, side: side)
        case .site:
            SiteIcon(site: face.site ?? face.label, label: face.label, size: side <= 16 ? .inline : .row,
                     savedItem: face.id)
                .frame(width: side, height: side)
        }
    }
}

/// A Messages chat's face: the photo the chat shares (Cicada's own copy, `GET /sources/messages/chats/{id}/photo`),
/// else a ring with the first letter of who it is with — never a solid fill.
struct ChatFace: View {
    let id: String
    let label: String
    let photo: String?
    let side: CGFloat

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        ZStack {
            if let image {
                Image(nsImage: image).resizable().interpolation(.high).scaledToFill()
                    .frame(width: side, height: side)
                    .clipShape(Circle())
            } else {
                Circle().strokeBorder(CicadaTheme.border, lineWidth: 1)
                Text(SiteMonogram.letter(label))
                    .font(CicadaTheme.font(size: side * 0.5, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(id)|\(photo ?? "")") {
            guard let path = SourcePictures.chatPhotoPath((id, photo)) else { image = nil; return }
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "")
        }
    }
}
