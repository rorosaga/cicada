import Foundation

/// URL → video classification. Pure: no network, no I/O, never traps (plan R2).
///
/// Track V / R-V1: the provider is a **pure function of a URL the bank already
/// stores**, so it is DERIVED at read time rather than written into a bank.
/// That is what lets every already-saved Vimeo/TikTok/Loom/`.mp4` item play the
/// moment the app updates — no whole-bank rewrite commit and no parallel
/// `url_index.json` migration (`GET /sources` reads `media_type` from the index,
/// not the page, so migrating one and not the other is the split-brain class
/// this repo already knows). It is the same house rule `_state.md` (a cursor,
/// not a copy), `age_days` and `inbox_context`'s offsets already follow.
///
/// The twin implementation is `api/services/video_urls.py`, and both are pinned
/// by `api/tests/fixtures/video_urls.json` (R-V8). Edit the fixture first; the
/// other side then fails until it is taught too. The two must stay spelled
/// identically — `Provider`/`Kind` raw values ARE the fixture's strings.
///
/// What is NOT here, and why (R-V4 — the ToS rail):
///   * No stream resolution. No `yt-dlp`, no `googlevideo.com`, no `.m3u8`
///     lifted out of a page's HTML or JS, no provider CDN URL. A direct file
///     Cicada plays is one the USER saved as a direct URL.
///   * No network to classify. `vm.tiktok.com/<slug>` hides its id behind a
///     redirect, so it stays `external` rather than being resolved by a fetch.
///   * Twitch is `external`: its player validates `parent` against the real
///     embedding origin and a `WKWebView` loading the player as a top-level
///     document has none — synthesising one is circumventing an embed
///     restriction.
///   * X is absent: `x.com/<user>/status/<id>` is *any* post, so classifying
///     every status as a video would be a lie. Instagram is absent too — it is
///     login-walled and never plays in-app, and `MediaPreviewModel` already
///     owns it by host.
struct VideoRef: Equatable {
    /// Raw values are the fixture's `provider` column (R-V8) — never rename one
    /// without editing `api/tests/fixtures/video_urls.json` and the Python twin.
    enum Provider: String {
        case youtube, vimeo, tiktok, loom, twitch, direct, local
    }

    /// The *decision*, not a description:
    ///   * `embed`    — load `embedURL` in the provider's own player.
    ///   * `file`     — hand `watchURL` to AVKit.
    ///   * `external` — recognised as a video, deliberately not played in-app.
    ///                  The reason lives in this type's doc comment, not a TODO.
    enum Kind: String {
        case embed, file, external
    }

    let provider: Provider
    let kind: Kind
    /// `nil` for a file and for a YouTube playlist — there is no single video
    /// there, and the list id rides in `embedURL` instead.
    let videoId: String?
    let embedURL: URL?
    let watchURL: URL

    /// R6/R14: only these two get a player and a play badge. A badge on an
    /// `external` ref would promise playback the tap cannot deliver.
    var isPlayable: Bool { kind == .embed || kind == .file }

    /// R11: autoplay only where it is the provider's own documented player
    /// param and we verified it — YouTube and Vimeo. TikTok and Loom get their
    /// plain embed URL and the user presses play. Appended through
    /// `URLComponents` so Vimeo's unlisted `?h=<hash>` survives as
    /// `?h=<hash>&autoplay=1` rather than being overwritten.
    ///
    /// The HERO never uses this: a hero renders on every visit to the entity
    /// page rather than behind an explicit tap, so autoplaying there would be
    /// surprising. `HeroPreview` reads `embedURL` directly — the rule the
    /// YouTube-only `youtubeHeroEmbedURL` used to carry, now stated once.
    var autoplayURL: URL? {
        guard kind == .embed, let embedURL else { return nil }
        switch provider {
        case .youtube, .vimeo:
            guard var comps = URLComponents(url: embedURL, resolvingAgainstBaseURL: false) else {
                return embedURL
            }
            comps.queryItems = (comps.queryItems ?? []) + [URLQueryItem(name: "autoplay", value: "1")]
            return comps.url ?? embedURL
        case .tiktok, .loom, .twitch, .direct, .local:
            return embedURL
        }
    }

    /// R17: absent means absent. A provider that gave no duration renders
    /// nothing — never an estimate, the same rule the Sleep history's `—`
    /// duration follows (G125 R5).
    static func durationLabel(_ seconds: Int?) -> String? {
        guard let seconds, seconds > 0 else { return nil }
        let hours = seconds / 3600
        let minutes = (seconds % 3600) / 60
        let secs = seconds % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, secs) }
        return String(format: "%d:%02d", minutes, secs)
    }

    // MARK: - Resolution

    /// Path extensions AVKit can play directly (R3). Matched case-insensitively
    /// against the PATH only — an extension in a query string is not a file.
    private static let fileExtensions: Set<String> = ["mp4", "m4v", "mov", "webm", "m3u8"]

    /// Schemes that are ever classified (R2). Anything else — `javascript:`,
    /// `data:`, `mailto:` — is not a video no matter what it ends in.
    private static let schemes: Set<String> = ["http", "https", "file"]

    private static let youtubePathHeads: Set<String> = ["shorts", "embed", "v", "live"]

    /// Classify a URL. `nil` means "not a video" and is the only failure mode —
    /// a classifier that could trap would take a whole Feed row down with it.
    static func resolve(_ raw: String) -> VideoRef? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              let comps = URLComponents(string: trimmed),
              let scheme = comps.scheme?.lowercased(),
              schemes.contains(scheme),
              let watch = URL(string: trimmed)
        else { return nil }

        // `percentEncodedPath`, not `path`: the Python twin reads
        // `urlparse().path`, which does not decode either. Matching the two
        // parsers matters more than a prettier id.
        let path = comps.percentEncodedPath
        let host = (comps.host ?? "").lowercased()

        if scheme == "file" {
            guard !segments(path).isEmpty,
                  fileExtensions.contains(pathExtension(path))
            else { return nil }
            // R9: whether the file is READABLE is decided at render time, never
            // here — classification stays pure.
            return VideoRef(provider: .local, kind: .file, videoId: nil, embedURL: nil, watchURL: watch)
        }

        guard !host.isEmpty else { return nil }

        // A direct file wins over the host table: nothing in the table serves one.
        if fileExtensions.contains(pathExtension(path)) {
            return VideoRef(provider: .direct, kind: .file, videoId: nil, embedURL: nil, watchURL: watch)
        }

        if host.hasSuffix("youtu.be") || host.contains("youtube.com") || host.contains("youtube-nocookie.com") {
            return youtube(host: host, path: path, comps: comps, watch: watch)
        }
        if host == "vimeo.com" || host.hasSuffix(".vimeo.com") {
            return vimeo(path: path, watch: watch)
        }
        if host.contains("tiktok.com") {
            return tiktok(host: host, path: path, watch: watch)
        }
        if host.contains("loom.com") {
            return loom(path: path, watch: watch)
        }
        if host.contains("twitch.tv") {
            return twitch(host: host, path: path, watch: watch)
        }
        return nil
    }

    // MARK: - Per-provider tables (mirrors of the Python regexes)

    private static func youtube(host: String, path: String, comps: URLComponents, watch: URL) -> VideoRef? {
        var videoId: String?
        let segs = segments(path)
        if host.hasSuffix("youtu.be") {
            videoId = segs.first
        } else {
            if trimmedPath(path) == "/watch" {
                videoId = queryValue(comps, "v")
            }
            if videoId == nil, segs.count >= 2, youtubePathHeads.contains(segs[0]) {
                // `[^/?&#]+` in the Python twin: the id stops at the first `&`.
                let candidate = String(segs[1].prefix { $0 != "&" && $0 != "#" && $0 != "?" })
                if !candidate.isEmpty { videoId = candidate }
            }
            if videoId == nil, trimmedPath(path) == "/playlist", let list = queryValue(comps, "list") {
                // YouTube's own multi-video player. No single video id exists,
                // so `videoId` stays nil and the list id lives in the embed url.
                return VideoRef(
                    provider: .youtube, kind: .embed, videoId: nil,
                    embedURL: URL(string: "https://www.youtube-nocookie.com/embed/videoseries?list=\(list)"),
                    watchURL: watch)
            }
        }
        guard let videoId, !videoId.isEmpty else { return nil }
        return VideoRef(
            provider: .youtube, kind: .embed, videoId: videoId,
            embedURL: URL(string: "https://www.youtube-nocookie.com/embed/\(videoId)"),
            watchURL: watch)
    }

    private static func vimeo(path: String, watch: URL) -> VideoRef? {
        let segs = segments(path)
        // The id is the FIRST all-digit segment, so `/channels/<name>/<id>` and
        // `/video/<id>` both resolve without a per-shape special case.
        for (index, seg) in segs.enumerated() where isAllDigits(seg) {
            var embed = "https://player.vimeo.com/video/\(seg)"
            let next = index + 1 < segs.count ? segs[index + 1] : ""
            // Vimeo's own private-link param: an unlisted video is
            // `vimeo.com/<id>/<hash>` and embeds as `?h=<hash>`.
            if !next.isEmpty, !isAllDigits(next), isVimeoHash(next) {
                embed += "?h=\(next)"
            }
            return VideoRef(provider: .vimeo, kind: .embed, videoId: seg,
                            embedURL: URL(string: embed), watchURL: watch)
        }
        return nil
    }

    private static func tiktok(host: String, path: String, watch: URL) -> VideoRef? {
        if host.hasPrefix("vm.") || host.hasPrefix("vt.") {
            // R4: the id is only behind a redirect, and classifying costs no
            // network — so this is `external`, not a fetch waiting to happen.
            return VideoRef(provider: .tiktok, kind: .external, videoId: nil, embedURL: nil, watchURL: watch)
        }
        let segs = segments(path)
        var videoId: String?
        if segs.count >= 3, segs[0].hasPrefix("@"), segs[0].count > 1, segs[1] == "video" {
            videoId = digitPrefix(segs[2])
        }
        if videoId == nil, segs.count >= 3, segs[0] == "embed",
           segs[1].hasPrefix("v"), isAllDigits(String(segs[1].dropFirst())) {
            videoId = digitPrefix(segs[2])
        }
        guard let videoId, !videoId.isEmpty else { return nil }
        return VideoRef(provider: .tiktok, kind: .embed, videoId: videoId,
                        embedURL: URL(string: "https://www.tiktok.com/embed/v2/\(videoId)"),
                        watchURL: watch)
    }

    private static func loom(path: String, watch: URL) -> VideoRef? {
        let segs = segments(path)
        guard segs.count >= 2, segs[0] == "share" || segs[0] == "embed" else { return nil }
        let videoId = alphanumericPrefix(segs[1])
        guard !videoId.isEmpty else { return nil }
        return VideoRef(provider: .loom, kind: .embed, videoId: videoId,
                        embedURL: URL(string: "https://www.loom.com/embed/\(videoId)"),
                        watchURL: watch)
    }

    private static func twitch(host: String, path: String, watch: URL) -> VideoRef? {
        let segs = segments(path)
        if host.hasPrefix("clips.") {
            guard let slug = segs.first, !slug.isEmpty else { return nil }
            return VideoRef(provider: .twitch, kind: .external, videoId: slug, embedURL: nil, watchURL: watch)
        }
        guard segs.count >= 2, segs[0] == "videos" else { return nil }
        let videoId = digitPrefix(segs[1])
        guard !videoId.isEmpty else { return nil }
        return VideoRef(provider: .twitch, kind: .external, videoId: videoId, embedURL: nil, watchURL: watch)
    }

    // MARK: - String helpers

    private static func segments(_ path: String) -> [String] {
        path.split(separator: "/").map(String.init)
    }

    private static func trimmedPath(_ path: String) -> String {
        var out = path
        while out.count > 1, out.hasSuffix("/") { out.removeLast() }
        return out
    }

    private static func pathExtension(_ path: String) -> String {
        guard let tail = path.split(separator: "/").last, tail.contains(".") else { return "" }
        return String(tail.split(separator: ".").last ?? "").lowercased()
    }

    private static func queryValue(_ comps: URLComponents, _ name: String) -> String? {
        guard let value = comps.queryItems?.first(where: { $0.name == name })?.value, !value.isEmpty else {
            return nil
        }
        return value
    }

    private static func isAllDigits(_ s: String) -> Bool {
        !s.isEmpty && s.allSatisfy { $0.isASCII && $0.isNumber }
    }

    private static func isASCIIAlphanumeric(_ c: Character) -> Bool {
        c.isASCII && (c.isNumber || c.isLetter)
    }

    private static func digitPrefix(_ s: String) -> String {
        String(s.prefix { $0.isASCII && $0.isNumber })
    }

    private static func alphanumericPrefix(_ s: String) -> String {
        String(s.prefix(while: isASCIIAlphanumeric))
    }

    /// Vimeo's unlisted-link hash: alphanumeric, at least 4 characters, and not
    /// all digits (an all-digit follower would be another id, not a hash).
    private static func isVimeoHash(_ s: String) -> Bool {
        s.count >= 4 && s.allSatisfy(isASCIIAlphanumeric)
    }
}
