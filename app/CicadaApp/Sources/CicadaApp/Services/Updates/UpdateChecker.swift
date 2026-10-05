import Foundation

/// What one check found (G182).
enum UpdateCheckResult: Equatable, Sendable {
    case upToDate
    case available(UpdateManifest)
    /// Newer, but it needs a newer macOS than this Mac runs: never downloaded.
    case needsNewerMacOS(UpdateManifest, minimum: String)
}

/// G182 phase 5 — asks the release repo stamped into the app (`CicadaUpdateRepo`, `owner/repo`) for its newest
/// release, finds that release's `latest.json`, and compares versions. Two GETs, no cookies, nothing about the person
/// sent beyond the app's own version in the User-Agent. A pre-release is never "latest" on the releases API, so a
/// person only ever sees a published release. The fetch is injected; tests never touch the network.
struct UpdateChecker: Sendable {
    typealias Fetch = @Sendable (URLRequest) async throws -> (Data, HTTPURLResponse)

    static let repoInfoKey = "CicadaUpdateRepo"
    static let manifestAssetName = "latest.json"

    enum Failure: Error, Equatable {
        case noRepo
        case noRelease
        case http(Int)
        case noManifestAsset
        case badManifest
        case badVersion
        case insecureURL
        /// The manifest's zip isn't one of the same release's own assets.
        case foreignURL
        case offline
        case unreachable
        case other(String)

        /// A phrase that follows "Couldn't check for updates: ".
        var message: String {
            switch self {
            case .noRepo: Copy.Updates.reasonNoRepo
            case .noRelease: Copy.Updates.reasonNoRelease
            case .http(let code): Copy.Updates.reasonHTTP(code)
            case .noManifestAsset: Copy.Updates.reasonNoManifest
            case .badManifest: Copy.Updates.reasonBadManifest
            case .badVersion: Copy.Updates.reasonBadVersion
            case .insecureURL: Copy.Updates.reasonInsecure
            case .foreignURL: Copy.Updates.reasonForeignURL
            case .offline: Copy.Updates.reasonOffline
            case .unreachable: Copy.Updates.reasonUnreachable
            case .other(let s): s
            }
        }

        /// A transport error in the same plain words.
        static func from(_ error: Error) -> Failure {
            if let f = error as? Failure { return f }
            if let u = error as? URLError {
                switch u.code {
                case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed: return .offline
                case .timedOut, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed: return .unreachable
                default: break
                }
            }
            return .other(error.localizedDescription)
        }
    }

    let repo: String?
    let currentVersion: String?
    let osVersion: OperatingSystemVersion
    let fetch: Fetch

    init(repo: String?, currentVersion: String?,
         osVersion: OperatingSystemVersion = ProcessInfo.processInfo.operatingSystemVersion,
         fetch: @escaping Fetch = UpdateChecker.liveFetch) {
        self.repo = repo
        self.currentVersion = currentVersion
        self.osVersion = osVersion
        self.fetch = fetch
    }

    /// `owner/repo`, letters, digits, `-`, `_` and `.` only — the one shape that can be pasted into the API path.
    static func isValidRepo(_ repo: String?) -> Bool {
        guard let repo else { return false }
        return repo.range(of: #"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"#, options: .regularExpression) != nil
            && !repo.contains("..")
    }

    static func releasesURL(repo: String) -> URL? {
        guard isValidRepo(repo) else { return nil }
        return URL(string: "https://api.github.com/repos/\(repo)/releases/latest")
    }

    static func request(_ url: URL, version: String?, accept: String? = nil) -> URLRequest {
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        request.httpShouldHandleCookies = false
        if let accept { request.setValue(accept, forHTTPHeaderField: "Accept") }
        request.setValue("Cicada/\(version ?? "0")", forHTTPHeaderField: "User-Agent")
        return request
    }

    private struct Release: Decodable {
        struct Asset: Decodable {
            let name: String
            let browserDownloadURL: URL
            enum CodingKeys: String, CodingKey {
                case name
                case browserDownloadURL = "browser_download_url"
            }
        }
        let assets: [Asset]
    }

    func check() async throws -> UpdateCheckResult {
        guard let repo, let api = Self.releasesURL(repo: repo) else { throw Failure.noRepo }
        guard let current = currentVersion.flatMap(SemVer.init) else { throw Failure.badVersion }
        do {
            let (releaseData, releaseResponse) = try await fetch(
                Self.request(api, version: currentVersion, accept: "application/vnd.github+json"))
            if releaseResponse.statusCode == 404 { throw Failure.noRelease }
            guard releaseResponse.statusCode == 200 else { throw Failure.http(releaseResponse.statusCode) }
            guard let release = try? JSONDecoder().decode(Release.self, from: releaseData) else { throw Failure.badManifest }
            guard let asset = release.assets.first(where: { $0.name == Self.manifestAssetName }) else {
                throw Failure.noManifestAsset
            }
            guard asset.browserDownloadURL.scheme == "https" else { throw Failure.insecureURL }
            let (manifestData, manifestResponse) = try await fetch(Self.request(asset.browserDownloadURL,
                                                                                version: currentVersion))
            guard manifestResponse.statusCode == 200 else { throw Failure.http(manifestResponse.statusCode) }
            guard let manifest = try? UpdateManifest.decode(manifestData) else { throw Failure.badManifest }
            // The zip must be this release's own file: an https address equal to one of its assets' download URLs, so
            // a manifest can never point the download somewhere else (the signature would refuse it anyway; this
            // refuses it before a byte is fetched).
            guard manifest.url.scheme == "https" else { throw Failure.insecureURL }
            guard release.assets.contains(where: { $0.browserDownloadURL == manifest.url }) else {
                throw Failure.foreignURL
            }
            return try Self.compare(manifest, current: current, osVersion: osVersion)
        } catch {
            throw Failure.from(error)
        }
    }

    /// Newer iff the manifest's version is strictly greater; a newer one this Mac can't run is said, never fetched.
    static func compare(_ manifest: UpdateManifest, current: SemVer,
                        osVersion: OperatingSystemVersion) throws -> UpdateCheckResult {
        guard let offered = SemVer(manifest.version) else { throw Failure.badManifest }
        guard manifest.url.scheme == "https" else { throw Failure.insecureURL }
        guard offered > current else { return .upToDate }
        if let raw = manifest.minimumMacOS {
            guard let minimum = MacOSVersion.parse(raw) else { throw Failure.badManifest }
            if !MacOSVersion.satisfies(osVersion, minimum: minimum) {
                return .needsNewerMacOS(manifest, minimum: MacOSVersion.display(minimum))
            }
        }
        return .available(manifest)
    }

    /// An ephemeral session: no cookie jar, no cache on disk, nothing remembered between checks.
    static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 30
        return URLSession(configuration: config)
    }()

    static let liveFetch: Fetch = { request in
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (data, http)
    }
}
