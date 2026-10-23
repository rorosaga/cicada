import Foundation

/// G191 v7 — which reasons from the bank the panel suggests for one saved link (owner 2026-10-23: "more options that
/// appear smoothly based on the content being saved … from our bank").
///
/// **No generative model at save time** (the "No LLM at capture time" rail): the ranking is a table and a count,
/// computed on the Mac in microseconds and the same for the same inputs. Four signals, all local:
///
/// 1. **The site** — the platform the link is on (`sitePriors`: youtube.com leans to *To watch later* and *Asset for a
///    video*, pinterest.com to *For a moodboard*, github.com to *A tool to try* and *Code to reuse* …);
/// 2. **The link's own words** — its title and path (`wordPriors`: "recipe", "font", "podcast" …), never its query;
/// 3. **The person's own past picks** — what they chose before on this site, and overall, read from the answers the
///    bank already holds (`picks(from:)`, the Store's sources: nothing new is stored for it);
/// 4. **The search model's similarity**, only when the backend's EmbeddingGemma is already installed (never
///    downloaded for this) and it answered within `SaveWhyPolicy.suggestBudget` — else this term is simply absent.
///
/// The fixed row (`SavedWhyOptions.basic`) is never suggested: it is always there. A reason already chosen (an answer
/// being edited) is always shown first, so nothing selected is ever hidden.
enum SaveWhySuggest {
    /// What one earlier answer chose, and on which site.
    struct Pick: Equatable, Sendable {
        let site: String?
        let reasons: [String]
    }

    static let maxShown = 6
    static let minShown = 3
    /// Generic enough to fit anything, in this order, when the signals name fewer than `minShown`.
    static let fallback = ["inspiration", "reference", "idea"]

    // Weights: the site is the strongest signal, the person's own picks on that site next, the words after; a model's
    // similarity can lift a reason the tables do not know, never bury one the person picks.
    static let siteWeight = 3.0
    static let wordWeight = 2.0
    static let sitePickWeight = 1.5
    static let sitePickCap = 3
    static let pickWeight = 0.4
    static let pickCap = 5
    static let modelWeight = 2.0

    /// The platform's leanings: a site (its registrable domain, or a host ending in it) → reasons with a weight in 0…1.
    static let sitePriors: [(sites: [String], reasons: [(String, Double)])] = [
        (["youtube.com", "youtu.be", "vimeo.com"],
         [("to_watch", 1), ("video_asset", 0.9), ("how_to", 0.6), ("funny", 0.5), ("music", 0.4), ("to_learn", 0.4)]),
        (["tiktok.com"], [("funny", 1), ("video_asset", 0.9), ("inspiration", 0.5), ("recipe", 0.4)]),
        (["instagram.com"],
         [("aesthetic", 1), ("inspiration", 0.9), ("funny", 0.7), ("moodboard", 0.7), ("photo", 0.6), ("outfit", 0.5),
          ("place", 0.4)]),
        (["pinterest.com", "pin.it"],
         [("moodboard", 1), ("aesthetic", 0.9), ("inspiration", 0.8), ("palette", 0.6), ("recipe", 0.5),
          ("outfit", 0.5), ("home", 0.5)]),
        (["x.com", "twitter.com", "threads.net", "bsky.app"],
         [("funny", 0.8), ("idea", 0.8), ("quote", 0.6), ("to_share", 0.6), ("news", 0.5),
          ("someone_to_follow", 0.5)]),
        (["linkedin.com"], [("for_work", 1), ("someone_to_follow", 0.8), ("advice", 0.6), ("idea", 0.6)]),
        (["github.com", "gitlab.com", "codeberg.org", "huggingface.co"],
         [("tool_to_try", 1), ("code", 0.9), ("reference", 0.6), ("to_learn", 0.5)]),
        (["dribbble.com", "behance.net", "awwwards.com", "mobbin.com", "figma.com", "siteinspire.com"],
         [("ui_pattern", 1), ("aesthetic", 0.8), ("moodboard", 0.7), ("inspiration", 0.7), ("typography", 0.5)]),
        (["fonts.google.com", "typewolf.com", "fontshare.com"], [("typography", 1), ("reference", 0.5)]),
        (["coolors.co", "colorhunt.co"], [("palette", 1), ("moodboard", 0.5)]),
        (["reddit.com"], [("funny", 0.8), ("advice", 0.8), ("idea", 0.5), ("to_share", 0.4)]),
        (["amazon.com", "amazon.co.uk", "amazon.de", "amazon.es", "amazon.fr", "amazon.it", "amazon.ca",
          "amazon.com.mx", "etsy.com", "ebay.com", "aliexpress.com"],
         [("to_buy", 1), ("gift_idea", 0.8), ("product_idea", 0.3)]),
        (["producthunt.com", "apps.apple.com"], [("tool_to_try", 1), ("product_idea", 0.7)]),
        (["spotify.com", "soundcloud.com", "music.apple.com", "bandcamp.com", "podcasts.apple.com"],
         [("to_listen", 1), ("music", 0.9)]),
        (["arxiv.org", "doi.org", "nature.com", "sciencedirect.com", "semanticscholar.org", "scholar.google.com"],
         [("research", 1), ("to_learn", 0.7), ("reference", 0.6)]),
        (["medium.com", "substack.com", "paulgraham.com"], [("good_writing", 0.8), ("idea", 0.7), ("to_learn", 0.5)]),
        (["nytimes.com", "theguardian.com", "bbc.co.uk", "bbc.com", "reuters.com", "elpais.com"],
         [("news", 1), ("to_share", 0.4), ("good_writing", 0.3)]),
        (["airbnb.com", "booking.com", "tripadvisor.com", "maps.google.com", "maps.apple.com"],
         [("place", 1), ("travel", 0.9)]),
        (["unsplash.com", "500px.com", "flickr.com"], [("photo", 1), ("aesthetic", 0.7), ("moodboard", 0.6)]),
        (["artstation.com", "deviantart.com"], [("art", 1), ("inspiration", 0.7), ("moodboard", 0.5)]),
        (["eventbrite.com", "meetup.com", "lu.ma", "luma.com"], [("event", 1), ("someone_to_follow", 0.3)]),
    ]

    /// A word in the title or the path (whole words, lower-cased) → a reason with a weight in 0…1.
    static let wordPriors: [(words: [String], reason: String, weight: Double)] = [
        (["recipe", "recipes", "receta", "recetas", "cooking", "baking"], "recipe", 1),
        (["how", "tutorial", "guide", "howto", "walkthrough"], "how_to", 0.7),
        (["course", "lesson", "learn", "lecture", "explained"], "to_learn", 0.8),
        (["font", "fonts", "typeface", "typography", "type"], "typography", 0.8),
        (["palette", "palettes", "colour", "colours", "color", "colors"], "palette", 0.8),
        (["podcast", "episode", "album", "song", "playlist", "mix"], "to_listen", 0.8),
        (["paper", "study", "pdf", "preprint", "abstract"], "research", 0.8),
        (["quote", "quotes"], "quote", 0.9),
        (["gift", "gifts", "regalo"], "gift_idea", 1),
        (["buy", "shop", "store", "price", "sale", "deal", "pricing"], "to_buy", 0.6),
        (["workout", "exercise", "training", "routine", "gym"], "workout", 1),
        (["travel", "hotel", "trip", "itinerary", "flights"], "travel", 0.9),
        (["ui", "ux", "component", "components", "dashboard", "onboarding", "interface"], "ui_pattern", 0.7),
        (["meme", "memes", "funny", "lol", "comedy"], "funny", 1),
        (["conference", "meetup", "event", "tickets", "festival"], "event", 0.9),
        (["job", "jobs", "hiring", "career", "careers", "salary"], "for_work", 0.9),
        (["trailer", "film", "movie", "documentary", "watch"], "to_watch", 0.6),
        (["library", "framework", "sdk", "cli", "api", "plugin"], "tool_to_try", 0.6),
        (["snippet", "gist", "example", "examples"], "code", 0.6),
        (["data", "dataset", "chart", "charts", "statistics", "survey"], "data", 0.8),
        (["essay", "letter", "manifesto"], "good_writing", 0.7),
        (["interior", "furniture", "decor", "kitchen", "garden"], "home", 0.8),
        (["outfit", "fashion", "streetwear", "style"], "outfit", 0.8),
        (["photo", "photography", "photos"], "photo", 0.7),
        (["illustration", "painting", "drawing", "artwork"], "art", 0.8),
        (["tips", "advice", "lessons", "mistakes"], "advice", 0.7),
    ]

    /// The suggestions for `item`, in the order shown: `minShown`…`maxShown` reasons from `bank` (never the fixed row),
    /// a reason in `pinned` (already chosen) always first.
    static func rank(url: String, title: String, bank: [SavedWhyOptions.Reason], picks: [Pick],
                     model: [String: Double]? = nil, pinned: [String] = []) -> [SavedWhyOptions.Reason] {
        let keys = bank.map(\.key)
        guard !keys.isEmpty else { return [] }
        let score = scores(url: url, title: title, keys: keys, picks: picks, model: model)
        let index = Dictionary(keys.enumerated().map { ($1, $0) }, uniquingKeysWith: { first, _ in first })
        let byScore = keys.filter { (score[$0] ?? 0) > 0 }
            .sorted { (score[$0] ?? 0, -(index[$0] ?? 0)) > (score[$1] ?? 0, -(index[$1] ?? 0)) }
        var chosen = pinned.filter(index.keys.contains)
        for key in byScore + fallback + keys where chosen.count < max(minShown, min(maxShown, byScore.count)) {
            if index[key] != nil, !chosen.contains(key) { chosen.append(key) }
        }
        let labels = Dictionary(bank.map { ($0.key, $0) }, uniquingKeysWith: { first, _ in first })
        return chosen.compactMap { labels[$0] }
    }

    /// Each bank key's score from the four signals (absent: zero). Public for the tests.
    static func scores(url: String, title: String, keys: [String], picks: [Pick],
                       model: [String: Double]?) -> [String: Double] {
        let known = Set(keys)
        var score: [String: Double] = [:]
        func add(_ key: String, _ value: Double) {
            guard known.contains(key), value > 0 else { return }
            score[key, default: 0] += value
        }
        let site = self.site(of: url)
        if let site {
            for prior in sitePriors where prior.sites.contains(where: { matches(site: site, $0, host: host(of: url)) }) {
                for (key, weight) in prior.reasons { add(key, siteWeight * weight) }
            }
        }
        let words = Set(self.words(title: title, url: url))
        for prior in wordPriors where !words.isDisjoint(with: prior.words) {
            add(prior.reason, wordWeight * prior.weight)
        }
        var onSite: [String: Int] = [:]
        var overall: [String: Int] = [:]
        for pick in picks {
            for key in Set(pick.reasons) where known.contains(key) {
                overall[key, default: 0] += 1
                if let site, pick.site == site { onSite[key, default: 0] += 1 }
            }
        }
        for (key, n) in onSite { add(key, sitePickWeight * Double(min(n, sitePickCap))) }
        for (key, n) in overall { add(key, pickWeight * Double(min(n, pickCap))) }
        if let model {
            let values = keys.compactMap { model[$0] }
            if let low = values.min(), let high = values.max(), high > low {
                for key in keys { if let s = model[key] { add(key, modelWeight * (s - low) / (high - low)) } }
            }
        }
        return score
    }

    /// Every earlier answer in the bank as a pick: the link's site and the reasons chosen (each answer once — a link
    /// saved three times with three answers counts three times, as the person chose three times).
    static func picks(from items: [MediaFeedItem]) -> [Pick] {
        items.flatMap { item in
            item.savedWhyAnswers.filter { !$0.reasons.isEmpty }.map { Pick(site: site(of: item.url), reasons: $0.reasons) }
        }
    }

    // MARK: - Reading a link

    /// The host, lower-cased, without `www.` / `m.` / `mobile.`.
    static func host(of url: String) -> String? {
        guard var host = URL(string: url.trimmingCharacters(in: .whitespacesAndNewlines))?.host?.lowercased(),
              !host.isEmpty else { return nil }
        for prefix in ["www.", "m.", "mobile."] where host.hasPrefix(prefix) { host.removeFirst(prefix.count) }
        return host
    }

    /// The registrable domain ("music.youtube.com" → "youtube.com", "bbc.co.uk" stays): the key a past pick is matched
    /// on, so the same platform's subdomains count together.
    static func site(of url: String) -> String? {
        guard let host = host(of: url) else { return nil }
        let labels = host.split(separator: ".").map(String.init)
        guard labels.count > 2 else { return host }
        let secondLevel: Set<String> = ["co", "com", "org", "net", "ac", "gov", "edu"]
        let keep = labels[labels.count - 1].count == 2 && secondLevel.contains(labels[labels.count - 2]) ? 3 : 2
        return labels.suffix(keep).joined(separator: ".")
    }

    /// A prior's site matches the link's registrable domain, or — for a prior naming a subdomain
    /// ("music.apple.com") — the host itself or a host ending in it.
    static func matches(site: String, _ prior: String, host: String?) -> Bool {
        if site == prior { return true }
        guard let host else { return false }
        return host == prior || host.hasSuffix("." + prior)
    }

    /// The title's and the path's words, lower-cased, letters and digits only; never the query or fragment.
    static func words(title: String, url: String) -> [String] {
        let path = URLComponents(string: url)?.path ?? ""
        return "\(title) \(path)".lowercased()
            .split { !$0.isLetter && !$0.isNumber }
            .map(String.init)
    }
}
