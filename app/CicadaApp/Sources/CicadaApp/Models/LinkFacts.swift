import Foundation

/// What Cicada knows about one URL a page links to (`GET /entities/{id}/links`, owner rulings 2026-10-14): every fact a
/// link card draws. Nothing was fetched to answer — a URL Cicada never read carries only its site.
struct LinkFact: Decodable, Equatable, Sendable {
    struct Capture: Decodable, Equatable, Sendable {
        var day: String
        var at: String?
        var kind: String
        var image: String
    }

    struct Look: Decodable, Equatable, Sendable {
        var id: String
        var day: String
        var image: String
        var palette: [DesignColour]
    }

    var url: String
    var views: [String] = []
    var site: String?
    var pageId: String?
    var title: String?
    var description: String?
    var savedAt: String?
    var readAt: String?
    var preview: String?
    var captures: [Capture] = []
    var looks: [Look] = []
    /// The page's icon route serves this site's mark (a trusted source, or a page the person saved).
    var icon: Bool = false

    init(url: String, site: String? = nil, pageId: String? = nil, title: String? = nil, description: String? = nil,
         savedAt: String? = nil, readAt: String? = nil, preview: String? = nil, captures: [Capture] = [],
         looks: [Look] = [], icon: Bool = false) {
        self.url = url
        self.site = site
        self.pageId = pageId
        self.title = title
        self.description = description
        self.savedAt = savedAt
        self.readAt = readAt
        self.preview = preview
        self.captures = captures
        self.looks = looks
        self.icon = icon
    }

    enum CodingKeys: String, CodingKey {
        case url, views, site, pageId, title, description, savedAt, readAt, preview, captures, looks, icon
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        views = (try? c.decodeIfPresent([String].self, forKey: .views)) ?? []
        site = try? c.decodeIfPresent(String.self, forKey: .site)
        pageId = try? c.decodeIfPresent(String.self, forKey: .pageId)
        title = try? c.decodeIfPresent(String.self, forKey: .title)
        description = try? c.decodeIfPresent(String.self, forKey: .description)
        savedAt = try? c.decodeIfPresent(String.self, forKey: .savedAt)
        readAt = try? c.decodeIfPresent(String.self, forKey: .readAt)
        preview = try? c.decodeIfPresent(String.self, forKey: .preview)
        captures = (try? c.decodeIfPresent([Capture].self, forKey: .captures)) ?? []
        looks = (try? c.decodeIfPresent([Look].self, forKey: .looks)) ?? []
        icon = (try? c.decodeIfPresent(Bool.self, forKey: .icon)) ?? false
    }

    /// The fact for a URL Cicada knows nothing more about: its site, from the URL.
    static func unknown(_ url: String) -> LinkFact { LinkFact(url: url, site: LinkGrammar.site(url)) }
}

struct PageLinkFacts: Decodable, Equatable, Sendable {
    var entityId: String
    var links: [LinkFact]

    func fact(for url: String) -> LinkFact? { links.first { $0.url == url } }
}

/// The pure half of a link card: which picture, which date line, which views the switcher offers — tested without a
/// view (`LinkCardTests`). DR-58: every relative date is computed here, at read, never stored.
enum LinkCardModel {
    /// The one date line a card carries — the date of what is shown (design §4): "Read Oct 2" when Cicada read the
    /// site's words, else "Saved Oct 2", else nothing (a link never read says "Not read yet" in its card instead).
    static func dateLine(_ fact: LinkFact, locale: Locale = .autoupdatingCurrent) -> String? {
        if let read = EntityDates.shortDay(fact.readAt, locale: locale) { return Copy.Links.read(read) }
        if let saved = EntityDates.shortDay(fact.savedAt, locale: locale) { return Copy.Links.saved(saved) }
        return nil
    }

    /// The title a card shows: the page's own label, unless it is the URL itself — then the title Cicada knows, else
    /// the URL's short form. Never written back.
    static func title(_ ref: LinkRef?, fact: LinkFact) -> String {
        if let ref, ref.label != ref.url, !ref.label.isEmpty { return ref.label }
        if let title = fact.title, !title.isEmpty { return title }
        return LinkGrammar.display(fact.url)
    }

    /// A card's last line beside the site's mark (owner 2026-10-26, research-hub's bookmark): the link's address, then
    /// the one date line — "example.com/guide · Read Oct 2", else "· Not read yet".
    static func footer(_ fact: LinkFact) -> String {
        "\(LinkGrammar.display(fact.url)) · \(dateLine(fact) ?? Copy.Links.notRead)"
    }

    /// A picture of the page for the screenshot view: a capture from that day (else the nearest earlier, else the
    /// newest), standing in a saved look's screenshot until site exploration lands. Nil: no picture of it yet.
    struct Shot: Equatable {
        let image: String
        let day: String
        /// The day the link asked for, when the picture is from another one.
        let asked: String?
        let fromLook: Bool
    }

    static func shot(_ fact: LinkFact, day: String? = nil) -> Shot? {
        let pictures: [(image: String, day: String, look: Bool)] =
            fact.captures.map { ($0.image, $0.day, false) } + fact.looks.map { ($0.image, $0.day, true) }
        guard !pictures.isEmpty else { return nil }
        let newestFirst = pictures.sorted { $0.day > $1.day }
        guard let day else {
            let p = newestFirst[0]
            return Shot(image: p.image, day: p.day, asked: nil, fromLook: p.look)
        }
        if let exact = newestFirst.first(where: { $0.day == day }) {
            return Shot(image: exact.image, day: exact.day, asked: nil, fromLook: exact.look)
        }
        let p = newestFirst.first(where: { $0.day < day }) ?? newestFirst.last!
        return Shot(image: p.image, day: p.day, asked: day, fromLook: p.look)
    }

    /// The saved look a `look` view draws: the one from that day, else the newest.
    static func look(_ fact: LinkFact, day: String? = nil) -> LinkFact.Look? {
        if let day, let exact = fact.looks.first(where: { $0.day == day }) { return exact }
        return fact.looks.first
    }

    /// "Captured Oct 14, 2026 · 3 months ago" — the year dropped in the current year, the age computed now.
    static func capturedLine(_ shot: Shot, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                             calendar: Calendar = .current) -> String {
        let sameYear = InboxAge.date(shot.day).map {
            calendar.component(.year, from: $0) == calendar.component(.year, from: now)
        } ?? true
        let day = (sameYear ? EntityDates.shortDay(shot.day, locale: locale)
                            : EntityDates.day(shot.day, locale: locale)) ?? shot.day
        let age = InboxAge.phrase(days: InboxAge.days(since: shot.day, now: now))
        let head = shot.fromLook ? Copy.Links.savedToLooks(day) : Copy.Links.captured(day)
        if let asked = shot.asked, let askedDay = EntityDates.shortDay(asked, locale: locale) {
            return Copy.Links.nearest(head, asked: askedDay)
        }
        return "\(head) · \(age)"
    }

    /// The views a link's menu offers (owner 2026-10-26, Notion's model): Mention and URL always; Bookmark only for a
    /// link alone on its line (a block view in a sentence would draw as a mention anyway); Embed only for a link alone
    /// on its line that has something to embed (`LinkEmbed`: a video's own player, a PDF); then Screenshot, Captures
    /// and Look only where Cicada has a picture, a capture or a saved look. The view the link draws as now is always
    /// offered, so the menu can check it.
    /// A bare URL or `<URL>` is never switched: it is the page's own words, not a link token to restyle.
    static func offered(_ ref: LinkRef, fact: LinkFact) -> [LinkViewKind] {
        guard ref.markdown.hasPrefix("[") else { return [] }
        let now = current(ref)
        return LinkViewKind.switcher.filter { view in
            if view == now { return true }
            switch view {
            case .mention, .url: return true
            case .bookmark: return ref.block
            case .embed: return ref.block && LinkEmbed.of(ref.url) != nil
            case .screenshot: return ref.block && (!fact.captures.isEmpty || !fact.looks.isEmpty)
            case .captures: return ref.block && !fact.captures.isEmpty
            case .look: return ref.block && !fact.looks.isEmpty
            case .link, .raw: return false
            }
        }
    }

    /// The view a link draws as now, as its menu checks it: its own view word, else the context's default
    /// (`LinkGrammar.drawn`). An `embed` with nothing to embed is research-hub's reading of the word, a screenshot; an
    /// explicit `"raw"` is the plain link the menu calls URL.
    static func current(_ ref: LinkRef) -> LinkViewKind {
        switch LinkGrammar.drawn(ref) {
        case .embed: return LinkEmbed.of(ref.url) != nil ? .embed : .screenshot
        case .raw, .link: return .url
        case let view: return view
        }
    }

    /// The token a menu choice writes: the link with that view's word (the person's choice is always written, so a
    /// later change of the context's default never undoes it). Nil when it is the token already on the page.
    static func token(_ ref: LinkRef, choosing view: LinkViewKind) -> String? {
        let new = LinkGrammar.markdown(label: ref.label, url: ref.url, view: view,
                                       day: view == ref.asked ? ref.day : nil)
        return new == ref.markdown ? nil : new
    }
}

/// What an `embed` draws (owner 2026-10-26: "Embed video" for a video, "Embed" for a PDF): a video's own player — the
/// player URL `VideoRef` derives from the link, never one a provider returned (G162) — or a PDF's card. Nil: nothing to
/// embed, and the menu offers no Embed. Pure: no network.
enum LinkEmbed: Equatable {
    case video(player: URL)
    case pdf

    static func of(_ url: String) -> LinkEmbed? {
        if let ref = VideoRef.resolve(url), ref.kind == .embed, let player = ref.embedURL { return .video(player: player) }
        return isPDF(url) ? .pdf : nil
    }

    /// A web link to a PDF: its path ends in `.pdf`, or an arXiv `/pdf/` link.
    static func isPDF(_ raw: String) -> Bool {
        guard let comps = URLComponents(string: raw), let scheme = comps.scheme?.lowercased(),
              scheme == "https" || scheme == "http" else { return false }
        let path = comps.path.lowercased()
        if path.hasSuffix(".pdf") { return true }
        let host = (comps.host ?? "").lowercased()
        return (host == "arxiv.org" || host.hasSuffix(".arxiv.org")) && path.hasPrefix("/pdf/")
    }
}
