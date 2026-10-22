import XCTest
@testable import CicadaApp

/// Owner 2026-10-20 — "Instead of the Chrome logo make this an app-wide change": one rule for a saved link's main
/// mark on every surface (`SavedLinkMarkModel`), its site's own icon asked by an id, bounded and cached per site.
final class SavedLinkMarkTests: XCTestCase {
    private func feedItem(_ id: String, url: String, siteKey: String?, site: String? = nil,
                          origin: String = "chrome-bookmark") throws -> MediaFeedItem {
        var json: [String: Any] = ["mediaEntityId": id, "url": url, "title": "Title \(id)", "mediaType": "bookmark",
                                   "savedAt": "2026-10-01T00:00:00Z", "tags": [], "status": "active",
                                   "relatedCount": 0, "relevance": 0, "origin": origin]
        if let siteKey { json["siteKey"] = siteKey }
        if let site { json["site"] = site }
        return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func episode(_ id: String, origin: String, site: String?, copyKind: String = "link",
                         copyValue: String = "https://www.paperfold.io/a") throws -> EpisodeQueueItem {
        var json: [String: Any] = ["id": id, "timestamp": "2026-10-01T00:00:00Z", "source": origin, "origin": origin,
                                   "preview": "", "processed": false, "copyKind": copyKind, "copyValue": copyValue]
        if let site { json["site"] = site }
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    func testASavedRowWearsItsSiteNeverTheBrowser() throws {
        let item = try feedItem("m1", url: "https://www.paperfold.io/a", siteKey: "paperfold.io", site: "paperfold.io")
        XCTAssertEqual(SavedLinkMarkModel.mark(item), .site(key: "paperfold.io", label: "paperfold.io", door: .media("m1")))
        let older = try feedItem("m2", url: "https://www.paperfold.io/b", siteKey: nil)
        XCTAssertNil(SavedLinkMarkModel.mark(older), "an older backend names no site: the row keeps the mark it had")
    }

    func testAWaitingBookmarkIsAskedByItsEpisodeUntilSleepMadeItsPage() throws {
        let waiting = try episode("ep_2026-10-01_1", origin: "chrome-bookmark", site: "paperfold.io")
        XCTAssertEqual(SavedLinkMarkModel.mark(waiting),
                       .site(key: "paperfold.io", label: "paperfold.io", door: .episode("ep_2026-10-01_1")))
        let family = try episode("ep_2026-10-01_2", origin: "chrome-bookmark", site: "linkedin",
                                 copyValue: "https://www.linkedin.com/posts/x")
        XCTAssertEqual(SavedLinkMarkModel.mark(family),
                       .site(key: "linkedin", label: "linkedin.com", door: .episode("ep_2026-10-01_2")))
        let conversation = try episode("ep_2026-10-01_3", origin: "claude-code", site: nil, copyKind: "conversation",
                                       copyValue: "s-1")
        XCTAssertNil(SavedLinkMarkModel.mark(conversation), "a conversation keeps its harness's real mark (DR-52)")
    }

    func testNoSiteIsAMonogramOfTheHostOrTitle() {
        XCTAssertEqual(SavedLinkMarkModel.mark(site: nil, host: "zebra.example", title: "Q", door: nil), .monogram("Z"))
        XCTAssertEqual(SavedLinkMarkModel.mark(site: "  ", host: nil, title: "quiet page", door: nil), .monogram("Q"))
    }

    func testTheReaderHeaderOfASavedLinkWearsItsSite() {
        let doc = EpisodeText(episode: "ep_2026-10-01_1", text: "x", title: "A page", origin: "chrome-bookmark")
        XCTAssertNil(ReaderHeader.siteMark(doc), "no site named: the origin's mark stays")
        var saved = doc
        saved.site = "paperfold.io"
        XCTAssertEqual(ReaderHeader.siteMark(saved),
                       .site(key: "paperfold.io", label: "paperfold.io", door: .episode("ep_2026-10-01_1")))
        var page = EpisodeText(episode: "media-1", kind: "page", text: "x")
        page.site = "paperfold.io"
        XCTAssertNil(ReaderHeader.siteMark(page), "a page keeps its own picture")
    }

    /// A page and a waiting episode of one site share one answer: the site is asked once.
    func testOneSiteIsAskedOnceWhicheverIdAsks() async {
        let asks = Asks()
        let icon = Self.png
        let store = SiteIconStore(fetch: { _ in XCTFail("never the icon-service route"); return nil },
                                  fetchForSaved: { id in await asks.add(id); return icon },
                                  fetchForSavedEpisode: { id in await asks.add(id); return icon })
        _ = await store.image(site: "paperfold.io", bank: "b", saved: .episode("ep_2026-10-01_1"))
        _ = await store.image(site: "paperfold.io", bank: "b", saved: .media("m1"))
        _ = await store.image(site: "other.io", bank: "b", saved: .media("m2"))
        let asked = await asks.ids
        XCTAssertEqual(asked, ["ep_2026-10-01_1", "m2"])
    }

    /// A 500-row list never bursts: at most `maxConcurrent` icons are on the wire at once, each site once.
    func testFiveHundredRowsNeverBurst() async {
        let gauge = Gauge()
        let icon = Self.png
        let store = SiteIconStore(fetch: { _ in nil }, fetchForSaved: { _ in
            await gauge.enter()
            try? await Task.sleep(nanoseconds: 2_000_000)
            await gauge.leave()
            return icon
        }, maxConcurrent: 4)
        await withTaskGroup(of: Void.self) { group in
            for i in 0..<500 {
                group.addTask { _ = await store.image(site: "site\(i % 50).example", bank: "b", saved: .media("m\(i)")) }
            }
        }
        let peak = await gauge.peak
        let total = await gauge.total
        XCTAssertLessThanOrEqual(peak, 4)
        XCTAssertEqual(total, 50, "one ask per site")
        let storePeak = await store.peakRunning
        XCTAssertLessThanOrEqual(storePeak, 4)
    }

    /// Review of #372 — one id's 404 (a page the route refuses) never hides the icon another id of that site is served.
    func testOneRefusedIdNeverHidesTheSitesIcon() async {
        let icon = Self.png
        let store = SiteIconStore(fetch: { _ in nil }, fetchForSaved: { id in id == "refused" ? nil : icon })
        let refused = await store.image(site: "paperfold.io", bank: "b", saved: .media("refused"))
        XCTAssertNil(refused)
        let served = await store.image(site: "paperfold.io", bank: "b", saved: .media("saved-1"))
        XCTAssertNotNil(served, "the miss was the refused id's, not the site's")
        let again = await store.image(site: "paperfold.io", bank: "b", saved: .episode("ep_2026-10-01_1"))
        XCTAssertNotNil(again, "a hit is the site's: every id of it shares it")
    }

    /// A 1×1 PNG `NSImage(data:)` accepts.
    static let png = Data(base64Encoded:
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")!

    /// A row that scrolled away before its turn asks nothing.
    func testACancelledRowAsksNothing() async {
        let asks = Asks()
        let gate = Gate()
        let store = SiteIconStore(fetch: { _ in nil }, fetchForSaved: { id in
            await asks.add(id)
            await gate.wait()
            return nil
        }, maxConcurrent: 1)
        let first = Task { await store.image(site: "a.example", bank: "b", saved: .media("m1")) }
        while await asks.ids.isEmpty { await Task.yield() }
        let second = Task { await store.image(site: "b.example", bank: "b", saved: .media("m2")) }
        for _ in 0..<50 { await Task.yield() }
        second.cancel()
        await gate.open()
        _ = await first.value
        _ = await second.value
        let asked = await asks.ids
        XCTAssertEqual(asked, ["m1"])
    }
}

private actor Asks {
    var ids: [String] = []
    func add(_ id: String) { ids.append(id) }
}

private actor Gauge {
    var now = 0, peak = 0, total = 0
    func enter() { now += 1; total += 1; peak = max(peak, now) }
    func leave() { now -= 1 }
}

private actor Gate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }
    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters.removeAll()
    }
}
