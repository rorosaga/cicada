import Foundation

/// C11 (G146, round-4 decision 9) — which rung of the picture precedence a page's picture came from. The server
/// resolves it (`api/services/entity_picture.py`); `EntityPictureResolver` below is its twin.
enum PictureSource: String, Codable, Sendable, CaseIterable {
    case upload, initials, contacts, logo, thumbnail
}

/// A page's resolved picture. `url` is nil only for `initials` — the person chose the monogram.
struct EntityPictureRef: Equatable, Hashable, Sendable {
    var url: String?
    var source: PictureSource

    /// The wire pair (`picture`, `pictureSource`). Nil when the server sent no rung, or an image rung without a URL: a
    /// malformed answer draws the fallback, never a broken image (plan R-PE5).
    static func wire(url: String?, source: String?) -> EntityPictureRef? {
        guard let raw = source, let source = PictureSource(rawValue: raw) else { return nil }
        if source == .initials { return EntityPictureRef(url: nil, source: .initials) }
        guard let url, !url.isEmpty else { return nil }
        return EntityPictureRef(url: url, source: source)
    }
}

/// The rung inputs the server resolved from — on `GET /entities/{id}` and every picture write's answer, so the app can
/// paint a removal before the server answers (R-PE10). `logo` is already the rung's eligibility AND availability.
struct PictureInputs: Codable, Equatable, Hashable, Sendable {
    var type: String
    var choice: String?
    var uploadSha: String?
    var contactsSha: String?
    var logo: Bool
    var thumbnail: String?

    init(type: String, choice: String? = nil, uploadSha: String? = nil, contactsSha: String? = nil,
         logo: Bool = false, thumbnail: String? = nil) {
        self.type = type
        self.choice = choice
        self.uploadSha = uploadSha
        self.contactsSha = contactsSha
        self.logo = logo
        self.thumbnail = thumbnail
    }

    enum CodingKeys: String, CodingKey { case type, choice, uploadSha, contactsSha, logo, thumbnail }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = (try? c.decodeIfPresent(String.self, forKey: .type)) ?? "concept"
        choice = (try? c.decodeIfPresent(String.self, forKey: .choice)) ?? nil
        uploadSha = (try? c.decodeIfPresent(String.self, forKey: .uploadSha)) ?? nil
        contactsSha = (try? c.decodeIfPresent(String.self, forKey: .contactsSha)) ?? nil
        logo = (try? c.decodeIfPresent(Bool.self, forKey: .logo)) ?? false
        thumbnail = (try? c.decodeIfPresent(String.self, forKey: .thumbnail)) ?? nil
    }
}

/// The twin of `entity_picture.resolve` (R-PE3): one precedence, one table — `api/tests/fixtures/entity_picture.json`
/// runs on both sides, so a rung added on one side only turns the other red (the `timeline_state.json` precedent).
/// A person reaches rungs 1–2 only, a media page only its thumbnail, everything else only a logo.
enum EntityPictureResolver {
    /// RFC 3986's unreserved set — exactly what Python's `quote(s, safe="")` leaves alone.
    private static let unreserved = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

    static func resolve(id: String, _ i: PictureInputs) -> EntityPictureRef? {
        let path = "/entities/\(quote(id))"
        if i.choice == "upload", isSha(i.uploadSha), let sha = i.uploadSha {
            return EntityPictureRef(url: "\(path)/picture?v=\(sha)", source: .upload)
        }
        if i.choice == "initials" { return EntityPictureRef(url: nil, source: .initials) }
        if i.type == "person" {
            guard isSha(i.contactsSha), let sha = i.contactsSha else { return nil }
            return EntityPictureRef(url: "\(path)/picture?v=\(sha)", source: .contacts)
        }
        if i.type == "media" {
            guard let thumbnail = i.thumbnail, isHTTPS(thumbnail) else { return nil }
            return EntityPictureRef(url: thumbnail, source: .thumbnail)
        }
        return i.logo ? EntityPictureRef(url: "\(path)/logo", source: .logo) : nil
    }

    /// What shows once the person's own choice is gone — a removal's paint (R-PE10), DELETE's answer.
    static func detected(id: String, _ i: PictureInputs) -> EntityPictureRef? {
        var bare = i
        bare.choice = nil
        bare.uploadSha = nil
        return resolve(id: id, bare)
    }

    static func quote(_ id: String) -> String { id.addingPercentEncoding(withAllowedCharacters: unreserved) ?? id }

    static func isSha(_ value: String?) -> Bool {
        guard let value, value.unicodeScalars.count == 12 else { return false }
        return value.unicodeScalars.allSatisfy { ("0"..."9").contains($0) || ("a"..."f").contains($0) }
    }

    static func isHTTPS(_ value: String?) -> Bool {
        guard let value, value.hasPrefix("https://"), value.unicodeScalars.count <= 2048 else { return false }
        return !value.unicodeScalars.contains { CharacterSet.whitespacesAndNewlines.contains($0) }
    }
}

/// R-PE6 — how a picture URL is loaded: a path on Cicada's own API with the bearer, a provider's https thumbnail with
/// nothing of Cicada's. Anything else is never loaded.
enum PictureURL: Hashable, Sendable {
    case api(path: String)
    case external(URL)

    static func parse(_ raw: String?) -> PictureURL? {
        guard let raw, !raw.isEmpty else { return nil }
        if raw.hasPrefix("/entities/"), !raw.contains(".."), !raw.contains("//") { return .api(path: raw) }
        if EntityPictureResolver.isHTTPS(raw), let url = URL(string: raw), url.scheme == "https", url.host != nil {
            return .external(url)
        }
        return nil
    }

    var cacheKey: String {
        switch self {
        case .api(let path): "api:\(path)"
        case .external(let url): "ext:\(url.absoluteString)"
        }
    }
}
