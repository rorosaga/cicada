import Foundation

/// Design taste (owner, 2026-10-14) — the wire of `GET /design`, `GET /design/{id}` and `POST /design/search`
/// (`api/routers/design.py`). The server reads the colours, the type and the words; the app decodes and shows them.
/// Not a Store domain: `LooksCache` holds them in memory, revalidated by ETag.

struct DesignColour: Decodable, Equatable, Hashable, Sendable {
    var hex: String
    var share: Double
    /// Looks v2: `ground`, `ink`, `accent` or `wash` — the ground first, then by salience, never by area.
    var role: String? = nil
    /// The page's CSS or computed styles name this colour.
    var declared: Bool? = nil
}

/// Looks v2 — one role of the page's computed type (`body`, `heading`, `subheading`, `caption`, `link`, `drop_cap`),
/// as the person's agent read it in the page (`design_tokens`). Sizes are CSS pixels.
struct DesignTypeRole: Decodable, Equatable, Hashable, Sendable {
    var role: String
    var family: String
    var generic: String?
    var size: Double?
    var weight: Int?
    var lineHeight: Double?
    var letterSpacing: Double?
    var color: String?
}

/// Looks v2 — a colour role: from the page's computed styles (`page`) or read from the screenshot (`pixels`).
struct DesignColourRole: Decodable, Equatable, Hashable, Sendable {
    var role: String
    var hex: String
    var source: String
}

/// Looks polish (owner, 2026-10-15: "an Aa with the font and the name, or fonts if several") — one family the page
/// renders, the roles and sizes it is used for, and "Aa" drawn by the page itself in that family when the capture drew
/// one (`image`, a transparent PNG from the bank). Without one the app sets "Aa" in the family's generic kind and says so.
struct DesignSpecimen: Decodable, Equatable, Hashable, Sendable {
    struct Role: Decodable, Equatable, Hashable, Sendable {
        var role: String
        var size: Double?
        var weight: Int?
    }

    var family: String
    var generic: String?
    var roles: [Role]
    var image: DesignImage?

    init(family: String, generic: String? = nil, roles: [Role] = [], image: DesignImage? = nil) {
        self.family = family; self.generic = generic; self.roles = roles; self.image = image
    }

    private enum CodingKeys: String, CodingKey { case family, generic, roles, image }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(family: try c.decode(String.self, forKey: .family),
                  generic: try c.decodeIfPresent(String.self, forKey: .generic),
                  roles: (try? c.decodeIfPresent([Role].self, forKey: .roles)) ?? [],
                  image: try? c.decodeIfPresent(DesignImage.self, forKey: .image))
    }
}

struct DesignImage: Decodable, Equatable, Hashable, Sendable {
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
    /// Looks v2 — who wrote the note: `user` (the person's own words, "What you liked") or the agent that saved it
    /// ("Noted by Claude Code"). An agent's note is never shown as the person's.
    var noteBy: String
    var noteByKind: String

    init(id: String, title: String = "", url: String? = nil, site: String? = nil, captured: String = "",
         day: String = "", addedBy: String = "user", addedByKind: String = "user", via: String = "drop",
         image: DesignImage? = nil, palette: [DesignColour] = [], look: [String] = [], fonts: [String] = [],
         tags: [String] = [], notePreview: String = "", entity: String? = nil, noteBy: String? = nil,
         noteByKind: String? = nil) {
        self.id = id; self.title = title; self.url = url; self.site = site; self.captured = captured; self.day = day
        self.addedBy = addedBy; self.addedByKind = addedByKind; self.via = via; self.image = image
        self.palette = palette; self.look = look; self.fonts = fonts; self.tags = tags
        self.notePreview = notePreview; self.entity = entity
        // An older server sends no `noteBy`: the note is the adder's, and an agent door's is never the person's.
        let inferred = noteBy ?? (via == "explore" ? "user" : (addedBy == "user" && via == "agent" ? "agent" : addedBy))
        self.noteBy = inferred
        self.noteByKind = noteByKind ?? (inferred == "user" ? "user" : "harness")
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, url, site, captured, day, addedBy, addedByKind, via, image, palette, look, fonts, tags,
             notePreview, entity, noteBy, noteByKind
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
            entity: try c.decodeIfPresent(String.self, forKey: .entity),
            noteBy: try c.decodeIfPresent(String.self, forKey: .noteBy),
            noteByKind: try c.decodeIfPresent(String.self, forKey: .noteByKind))
    }

    /// The note is the person's own words.
    var noteIsTheirs: Bool { noteBy == "user" }

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
    /// Looks v2 — the page's computed type by role, and its colour roles (ground, ink, accent, wash).
    var typeRoles: [DesignTypeRole]
    var colourRoles: [DesignColourRole]
    /// Looks polish — one specimen per family the page renders (at most six).
    var specimens: [DesignSpecimen]

    private enum CodingKeys: String, CodingKey { case note, snippets, path, typeRoles, colourRoles, specimens }

    init(summary: DesignRefSummary, note: String = "", snippets: [DesignSnippet] = [], path: String = "",
         typeRoles: [DesignTypeRole] = [], colourRoles: [DesignColourRole] = [], specimens: [DesignSpecimen] = []) {
        self.summary = summary; self.note = note; self.snippets = snippets; self.path = path
        self.typeRoles = typeRoles; self.colourRoles = colourRoles; self.specimens = specimens
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summary = try DesignRefSummary(from: decoder)
        note = try c.decodeIfPresent(String.self, forKey: .note) ?? ""
        snippets = try c.decodeIfPresent([DesignSnippet].self, forKey: .snippets) ?? []
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
        typeRoles = (try? c.decodeIfPresent([DesignTypeRole].self, forKey: .typeRoles)) ?? []
        colourRoles = (try? c.decodeIfPresent([DesignColourRole].self, forKey: .colourRoles)) ?? []
        specimens = (try? c.decodeIfPresent([DesignSpecimen].self, forKey: .specimens)) ?? []
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
