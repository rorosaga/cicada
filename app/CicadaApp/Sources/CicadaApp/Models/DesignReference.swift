import Foundation

/// Design taste (owner, 2026-10-14) — the wire of `GET /design`, `GET /design/{id}` and `POST /design/search`
/// (`api/routers/design.py`). The server reads the colours, the type and the words; the app decodes and shows them.
/// Not a Store domain: `LooksCache` holds them in memory, revalidated by ETag.

struct DesignColour: Decodable, Equatable, Hashable, Sendable {
    var hex: String
    var share: Double
}

struct DesignImage: Decodable, Equatable, Sendable {
    var url: String
    var width: Int
    var height: Int
    var bytes: Int

    /// Width over height, never zero — what a tile keeps while the picture loads.
    var aspect: Double { height > 0 && width > 0 ? Double(width) / Double(height) : 16.0 / 10.0 }
}

struct DesignSnippet: Decodable, Equatable, Sendable {
    var lang: String
    var code: String
}

struct DesignRefSummary: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    var url: String?
    var site: String?
    var captured: String
    var day: String
    var addedBy: String
    var addedByKind: String
    var via: String
    var image: DesignImage?
    var palette: [DesignColour]
    var look: [String]
    var fonts: [String]
    var tags: [String]
    var notePreview: String
    var entity: String?

    init(id: String, title: String = "", url: String? = nil, site: String? = nil, captured: String = "",
         day: String = "", addedBy: String = "user", addedByKind: String = "user", via: String = "drop",
         image: DesignImage? = nil, palette: [DesignColour] = [], look: [String] = [], fonts: [String] = [],
         tags: [String] = [], notePreview: String = "", entity: String? = nil) {
        self.id = id; self.title = title; self.url = url; self.site = site; self.captured = captured; self.day = day
        self.addedBy = addedBy; self.addedByKind = addedByKind; self.via = via; self.image = image
        self.palette = palette; self.look = look; self.fonts = fonts; self.tags = tags
        self.notePreview = notePreview; self.entity = entity
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, url, site, captured, day, addedBy, addedByKind, via, image, palette, look, fonts, tags,
             notePreview, entity
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try c.decode(String.self, forKey: .id),
            title: try c.decodeIfPresent(String.self, forKey: .title) ?? "",
            url: try c.decodeIfPresent(String.self, forKey: .url),
            site: try c.decodeIfPresent(String.self, forKey: .site),
            captured: try c.decodeIfPresent(String.self, forKey: .captured) ?? "",
            day: try c.decodeIfPresent(String.self, forKey: .day) ?? "",
            addedBy: try c.decodeIfPresent(String.self, forKey: .addedBy) ?? "user",
            addedByKind: try c.decodeIfPresent(String.self, forKey: .addedByKind) ?? "user",
            via: try c.decodeIfPresent(String.self, forKey: .via) ?? "drop",
            image: try c.decodeIfPresent(DesignImage.self, forKey: .image),
            palette: try c.decodeIfPresent([DesignColour].self, forKey: .palette) ?? [],
            look: try c.decodeIfPresent([String].self, forKey: .look) ?? [],
            fonts: try c.decodeIfPresent([String].self, forKey: .fonts) ?? [],
            tags: try c.decodeIfPresent([String].self, forKey: .tags) ?? [],
            notePreview: try c.decodeIfPresent(String.self, forKey: .notePreview) ?? "",
            entity: try c.decodeIfPresent(String.self, forKey: .entity))
    }

    /// The tile's name: the person's title, else the site, else "A look".
    var displayName: String {
        if !title.trimmingCharacters(in: .whitespaces).isEmpty { return title }
        if let site, !site.isEmpty { return site }
        return Copy.Looks.untitled
    }
}

struct DesignRef: Decodable, Equatable, Sendable {
    var summary: DesignRefSummary
    var note: String
    var snippets: [DesignSnippet]
    var path: String

    private enum CodingKeys: String, CodingKey { case note, snippets, path }

    init(summary: DesignRefSummary, note: String = "", snippets: [DesignSnippet] = [], path: String = "") {
        self.summary = summary; self.note = note; self.snippets = snippets; self.path = path
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summary = try DesignRefSummary(from: decoder)
        note = try c.decodeIfPresent(String.self, forKey: .note) ?? ""
        snippets = try c.decodeIfPresent([DesignSnippet].self, forKey: .snippets) ?? []
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
    }
}

/// Whether this Mac can search the board by picture, and the one-time download it would take.
struct DesignVision: Decodable, Equatable, Sendable {
    var supported: Bool
    var installed: Bool
    var downloadBytes: Int
    /// The size covers the meaning part too (fetched first when it isn't here) — said before the click.
    var includesText: Bool
    var installing: Bool
    var step: String
    var error: String

    init(supported: Bool = false, installed: Bool = false, downloadBytes: Int = 0, includesText: Bool = false,
         installing: Bool = false, step: String = "", error: String = "") {
        self.supported = supported; self.installed = installed; self.downloadBytes = downloadBytes
        self.includesText = includesText; self.installing = installing; self.step = step; self.error = error
    }

    private enum CodingKeys: String, CodingKey { case supported, installed, downloadBytes, includesText, installing, step, error }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(supported: try c.decodeIfPresent(Bool.self, forKey: .supported) ?? false,
                  installed: try c.decodeIfPresent(Bool.self, forKey: .installed) ?? false,
                  downloadBytes: try c.decodeIfPresent(Int.self, forKey: .downloadBytes) ?? 0,
                  includesText: try c.decodeIfPresent(Bool.self, forKey: .includesText) ?? false,
                  installing: try c.decodeIfPresent(Bool.self, forKey: .installing) ?? false,
                  step: try c.decodeIfPresent(String.self, forKey: .step) ?? "",
                  error: try c.decodeIfPresent(String.self, forKey: .error) ?? "")
    }
}

struct DesignBoard: Decodable, Equatable, Sendable {
    var refs: [DesignRefSummary]
    var vision: DesignVision
    var indexedImages: Int

    init(refs: [DesignRefSummary], vision: DesignVision = DesignVision(), indexedImages: Int = 0) {
        self.refs = refs; self.vision = vision; self.indexedImages = indexedImages
    }

    private enum CodingKeys: String, CodingKey { case refs, vision, indexedImages }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(refs: try c.decodeIfPresent([DesignRefSummary].self, forKey: .refs) ?? [],
                  vision: try c.decodeIfPresent(DesignVision.self, forKey: .vision) ?? DesignVision(),
                  indexedImages: try c.decodeIfPresent(Int.self, forKey: .indexedImages) ?? 0)
    }
}

struct DesignHit: Decodable, Equatable, Sendable {
    var id: String
    var score: Double
    var legs: [String]
}

struct DesignSearchResult: Decodable, Equatable, Sendable {
    var results: [DesignHit]
    var mode: String
    var missing: [String]
}

/// What the person hands the board: the screenshot's bytes (already shrunk, `DesignImageShrink`), the page, the note.
struct DesignUpload: Equatable, Sendable {
    var image: Data
    var ext: String
    var url: String?
    var title: String?
    var note: String?
    var via: String
}
