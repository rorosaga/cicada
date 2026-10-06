import Foundation

/// G182 phase 5 — `latest.json`, the one file each release publishes beside its zip: which version, where the zip is,
/// and the size, SHA-256 and Ed25519 signature the download must match before anything on disk changes. Pure: decoded
/// here, trusted nowhere until `UpdateVerifier` has checked the bytes it describes. Encodable too: a staged update
/// keeps its manifest in a sidecar (`UpdateInstaller.sidecarURL`) so a deferred install survives a relaunch.
struct UpdateManifest: Codable, Equatable, Sendable {
    let version: String
    let build: Int?
    let url: URL
    let size: Int64
    let sha256: String
    /// Base64 of a 64-byte Ed25519 signature over the zip's exact bytes.
    let signature: String
    let notesURL: URL?
    let minimumMacOS: String?
    let publishedAt: String?

    enum CodingKeys: String, CodingKey {
        case version, build, url, size, sha256, signature
        case notesURL = "notes_url"
        case minimumMacOS = "minimum_macos"
        case publishedAt = "published_at"
    }

    init(version: String, build: Int? = nil, url: URL, size: Int64, sha256: String, signature: String,
         notesURL: URL? = nil, minimumMacOS: String? = nil, publishedAt: String? = nil) {
        self.version = version
        self.build = build
        self.url = url
        self.size = size
        self.sha256 = sha256
        self.signature = signature
        self.notesURL = notesURL
        self.minimumMacOS = minimumMacOS
        self.publishedAt = publishedAt
    }

    static func decode(_ data: Data) throws -> UpdateManifest { try JSONDecoder().decode(UpdateManifest.self, from: data) }
}

/// G182 — a release version, `X.Y.Z` (a leading `v` is the tag's and is ignored). Anything else — a pre-release
/// suffix, two parts, a letter — is nil, so a malformed manifest can never look newer than the running app.
struct SemVer: Comparable, Hashable, Sendable, CustomStringConvertible {
    let major: Int
    let minor: Int
    let patch: Int

    init(major: Int, minor: Int, patch: Int) {
        self.major = major
        self.minor = minor
        self.patch = patch
    }

    init?(_ raw: String) {
        var text = raw.trimmingCharacters(in: .whitespaces)
        if text.hasPrefix("v") || text.hasPrefix("V") { text.removeFirst() }
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3 else { return nil }
        var numbers: [Int] = []
        for part in parts {
            guard !part.isEmpty, part.count <= 9, part.allSatisfy({ $0.isASCII && $0.isNumber }),
                  let n = Int(part) else { return nil }
            numbers.append(n)
        }
        self.init(major: numbers[0], minor: numbers[1], patch: numbers[2])
    }

    static func < (lhs: SemVer, rhs: SemVer) -> Bool {
        (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }

    var description: String { "\(major).\(minor).\(patch)" }
}

/// G182 — a manifest's `minimum_macos` ("14", "14.0", "14.2.1") as the system compares it; nil when it doesn't parse,
/// which refuses the update rather than guessing it would run.
enum MacOSVersion {
    static func parse(_ raw: String) -> OperatingSystemVersion? {
        let parts = raw.trimmingCharacters(in: .whitespaces).split(separator: ".", omittingEmptySubsequences: false)
        guard (1...3).contains(parts.count) else { return nil }
        var numbers: [Int] = []
        for part in parts {
            guard !part.isEmpty, part.allSatisfy({ $0.isASCII && $0.isNumber }), let n = Int(part) else { return nil }
            numbers.append(n)
        }
        while numbers.count < 3 { numbers.append(0) }
        return OperatingSystemVersion(majorVersion: numbers[0], minorVersion: numbers[1], patchVersion: numbers[2])
    }

    /// True when `running` is at least `minimum`.
    static func satisfies(_ running: OperatingSystemVersion, minimum: OperatingSystemVersion) -> Bool {
        (running.majorVersion, running.minorVersion, running.patchVersion)
            >= (minimum.majorVersion, minimum.minorVersion, minimum.patchVersion)
    }

    static func display(_ v: OperatingSystemVersion) -> String {
        v.patchVersion == 0 ? "\(v.majorVersion).\(v.minorVersion)" : "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
    }
}
