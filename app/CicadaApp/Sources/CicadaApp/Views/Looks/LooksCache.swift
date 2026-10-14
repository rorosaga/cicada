import AppKit
import Foundation
import Observation

/// Design taste (2026-10-14) — the Looks page's in-memory cache, `BacklogCache`'s twin: the board and the references
/// opened, revalidated with the server's ETag when the page appears, a write lands, or a sync event moves `design` or
/// the bank (`LooksRefresh`); emptied on a bank switch. Never blank: a failed or 304 answer keeps the last value
/// (DR-43). A search re-ranks the board the server already sent — the ids come back, the rows are the board's.
@Observable
@MainActor
final class LooksCache {
    enum Phase: Equatable { case idle, loading, loaded, failed(String) }

    private(set) var board: DesignBoard?
    private(set) var phase: Phase = .idle
    private(set) var refs: [String: DesignRef] = [:]
    /// The ids a search answered, best first; nil when no search is on.
    private(set) var ranking: [String]?
    private(set) var searchNote: String?
    private(set) var searching = false
    private(set) var saving = false
    private(set) var writeError: String?

    @ObservationIgnored private let api: any DesignAPI
    @ObservationIgnored private var etag: String?
    @ObservationIgnored private var refETags: [String: String] = [:]
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private var searchGeneration = 0

    init(api: any DesignAPI = APIClient.shared) { self.api = api }

    /// What the board shows: every reference, or a search's matches in its order.
    var visible: [DesignRefSummary] {
        guard let board else { return [] }
        guard let ranking else { return board.refs }
        let byId = Dictionary(uniqueKeysWithValues: board.refs.map { ($0.id, $0) })
        return ranking.compactMap { byId[$0] }
    }

    func reset() {
        epoch &+= 1
        board = nil
        phase = .idle
        refs = [:]
        ranking = nil
        searchNote = nil
        etag = nil
        refETags = [:]
    }

    func refresh() async {
        let started = epoch
        if board == nil { phase = .loading }
        do {
            let answer = try await api.fetchDesignBoard(etag: board == nil ? nil : etag)
            guard started == epoch else { return }
            if let value = answer.value {
                board = value
                etag = answer.etag
            }
            phase = .loaded
        } catch {
            guard started == epoch else { return }
            phase = board == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshRef(_ id: String) async {
        let started = epoch
        do {
            let answer = try await api.fetchDesignRef(id: id, etag: refs[id] == nil ? nil : refETags[id])
            guard started == epoch else { return }
            if let value = answer.value {
                refs[id] = value
                refETags[id] = answer.etag
            }
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            refs[id] = nil
        } catch {
            // Keep what is shown (DR-43); the summary still draws the column.
        }
    }

    func search(query: String, image: Data? = nil, ext: String? = nil) async {
        let words = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty || image != nil else {
            clearSearch()
            return
        }
        searchGeneration &+= 1
        let generation = searchGeneration
        let started = epoch
        searching = true
        defer { if generation == searchGeneration { searching = false } }
        do {
            let answer = try await api.searchDesign(query: words.isEmpty ? nil : words, image: image, ext: ext)
            guard started == epoch, generation == searchGeneration else { return }
            ranking = answer.results.map(\.id)
            searchNote = answer.missing.contains("image_model") && image != nil ? Copy.Looks.pictureMissing : nil
        } catch {
            guard started == epoch, generation == searchGeneration else { return }
            searchNote = Copy.Projects.loadFailed(error)
        }
    }

    func clearSearch() {
        searchGeneration &+= 1
        ranking = nil
        searchNote = nil
        searching = false
    }

    @discardableResult
    func save(_ upload: DesignUpload) async -> DesignRef? {
        saving = true
        writeError = nil
        defer { saving = false }
        do {
            let ref = try await api.saveDesignRef(upload)
            refs[ref.summary.id] = ref
            await refresh()
            return ref
        } catch {
            writeError = LooksErrors.sentence(error)
            return nil
        }
    }

    func remove(_ id: String) async {
        writeError = nil
        do {
            try await api.deleteDesignRef(id: id)
            refs[id] = nil
            if let ranking { self.ranking = ranking.filter { $0 != id } }
            await refresh()
        } catch {
            writeError = LooksErrors.sentence(error)
        }
    }

    func turnOnPictureSearch() async {
        do {
            try await api.installImageModel()
        } catch {
            writeError = LooksErrors.sentence(error)
        }
        await refresh()
    }

    /// The server's own sentence for a refusal it explains (409 demo or Sleep, 400/413 a bad picture); else generic.
    func clearError() { writeError = nil }
}

enum LooksErrors {
    static func sentence(_ error: Error) -> String {
        if case APIError.httpError(let code, let body) = error, [400, 409, 413].contains(code),
           let data = body.data(using: .utf8),
           let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String {
            return detail
        }
        return Copy.Projects.loadFailed(error)
    }
}

/// When the visible Looks page asks again: a sync version event that moved `design` (every reference file's stamp)
/// or the bank itself.
enum LooksRefresh {
    static let components = ["design", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}

/// A screenshot as the board keeps it: at most `maxSide` px on its longer side, a PNG when it is small enough to stay
/// lossless (≤ 1.5 MB), else a JPEG — so a 5K capture leaves the Mac under the server's 4 MB bound.
enum DesignImageShrink {
    static let maxSide: CGFloat = 2560
    static let pngLimit = 1_500_000

    static func prepare(_ image: NSImage) -> (data: Data, ext: String)? {
        guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        let w = CGFloat(cg.width), h = CGFloat(cg.height)
        let scale = min(1, maxSide / max(w, h, 1))
        let size = CGSize(width: max(1, (w * scale).rounded()), height: max(1, (h * scale).rounded()))
        guard let ctx = CGContext(data: nil, width: Int(size.width), height: Int(size.height), bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.setFillColor(CGColor(gray: 1, alpha: 1))
        ctx.fill(CGRect(origin: .zero, size: size))
        ctx.interpolationQuality = .high
        ctx.draw(cg, in: CGRect(origin: .zero, size: size))
        guard let out = ctx.makeImage() else { return nil }
        let rep = NSBitmapImageRep(cgImage: out)
        if let png = rep.representation(using: .png, properties: [:]), png.count <= pngLimit { return (png, "png") }
        guard let jpg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.85]) else { return nil }
        return (jpg, "jpg")
    }
}
