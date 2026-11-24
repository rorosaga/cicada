import Foundation

/// G246 (ruling 81, plan Track K) — "Keep as a page" on a saved post drawn as a row under its list, and the way back.
///
/// The backend decides everything (`keep_as_page.py`): which saves are posts, whether the person's own click or
/// something else holds a post's page. The app holds no rule; it draws what `GET /sources/keep-as-page` says and posts
/// the click. Until the posts-as-rows switch is on the answer is always `none`, so nothing here ever draws.

/// `GET /sources/keep-as-page?url=` — what a saved link's card may offer.
struct KeepAsPageState: Codable, Equatable, Sendable {
    /// `none` (no control), `row` ("Keep as a page"), `kept` (the person's click holds its page), `page` (something
    /// else earned it a page: no control). An unknown word is `none`.
    var state: String
    var canUndo: Bool
    /// Sign ids other than the person's click that hold the page (never a title).
    var becauseOf: [String]
    var mediaEntityId: String

    static let none = KeepAsPageState(state: "none", canUndo: false, becauseOf: [], mediaEntityId: "")

    init(state: String, canUndo: Bool, becauseOf: [String], mediaEntityId: String) {
        self.state = state
        self.canUndo = canUndo
        self.becauseOf = becauseOf
        self.mediaEntityId = mediaEntityId
    }

    enum CodingKeys: String, CodingKey { case state, canUndo, becauseOf, mediaEntityId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "none"
        canUndo = try c.decodeIfPresent(Bool.self, forKey: .canUndo) ?? false
        becauseOf = try c.decodeIfPresent([String].self, forKey: .becauseOf) ?? []
        mediaEntityId = try c.decodeIfPresent(String.self, forKey: .mediaEntityId) ?? ""
    }
}

/// `POST /sources/keep-as-page`'s answer: the state after, and what happened.
struct KeepAsPageReply: Codable, Equatable, Sendable {
    /// `kept`, `undone` or `unchanged`.
    var status: String
    var state: KeepAsPageState

    enum CodingKeys: String, CodingKey { case status, state, canUndo, becauseOf, mediaEntityId }

    init(status: String, state: KeepAsPageState) {
        self.status = status
        self.state = state
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "unchanged"
        state = try KeepAsPageState(from: decoder)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(status, forKey: .status)
        try c.encode(state.state, forKey: .state)
        try c.encode(state.canUndo, forKey: .canUndo)
        try c.encode(state.becauseOf, forKey: .becauseOf)
        try c.encode(state.mediaEntityId, forKey: .mediaEntityId)
    }
}

/// What the control draws and what pressing it asks for.
enum KeepAsPageOffer: Equatable, Sendable {
    /// A post drawn as a row: "Keep as a page".
    case keep
    /// A post the person's click holds, with nothing else holding it: "Back to a row".
    case back

    var title: String { self == .keep ? Copy.Keep.keep : Copy.Keep.back }
    var help: String { self == .keep ? Copy.Keep.keepHelp : Copy.Keep.backHelp }
    /// `kept` in the request body.
    var asksToKeep: Bool { self == .keep }
    /// The line said after it worked.
    var done: String { self == .keep ? Copy.Keep.kept : Copy.Keep.backed }
}

enum KeepAsPage {
    /// The one control a state offers, or nil: nothing for a work, a link not saved, a post some other reason holds a
    /// page for, a kept post that cannot go back, or any link while the switch is off.
    static func offer(_ state: KeepAsPageState?) -> KeepAsPageOffer? {
        switch state?.state {
        case "row": return .keep
        case "kept": return state?.canUndo == true ? .back : nil
        default: return nil
        }
    }

    /// The words for a click that did not land: the server's own sentence when it sent one for a refusal (a link not
    /// saved, a page held for another reason), a fixed one when Cicada is busy, else a plain retry.
    static func failureLine(_ error: Error) -> String {
        guard case APIError.httpError(let code, let body) = error else { return Copy.Keep.failed }
        if code == 409, body.contains("Sleep is updating") { return Copy.Keep.busy }
        if [404, 409, 422].contains(code), let sentence = detail(body) { return sentence }
        return Copy.Keep.failed
    }

    /// `{"detail": "…"}`'s sentence.
    static func detail(_ body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let text = object["detail"] as? String else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

/// Home's one dated line after the posts moved under their lists: how many, since which day this Mac first saw them.
/// Shown for a month, or until the person says "Got it". Nothing is stored in the bank; the day and the dismissal are
/// this Mac's own (`UserDefaults`, per memory). With the switch off `GraphResponse.hiddenPosts` is 0 and the record is
/// cleared, so nothing shows and a later flip starts a fresh month.
enum HiddenPostsNote {
    static let showForDays = 30

    struct Record: Equatable {
        var since: Date
        var dismissed: Bool
    }

    private static func key(_ bank: String) -> String { "cicada.hiddenPostsNote.\(bank)" }

    static func load(bank: String, defaults: UserDefaults = .standard) -> Record? {
        guard let raw = defaults.dictionary(forKey: key(bank)),
              let seconds = raw["since"] as? Double else { return nil }
        return Record(since: Date(timeIntervalSince1970: seconds), dismissed: raw["dismissed"] as? Bool ?? false)
    }

    private static func save(_ record: Record?, bank: String, defaults: UserDefaults) {
        if let record {
            defaults.set(["since": record.since.timeIntervalSince1970, "dismissed": record.dismissed], forKey: key(bank))
        } else {
            defaults.removeObject(forKey: key(bank))
        }
    }

    /// The record for this reading of the graph: none while nothing is hidden (and a stored one is forgotten), the
    /// stored one, or a new one dated `now` the first time a number shows. `hidden` is nil while the backend has not said
    /// (an empty snapshot after a memory switch or before a cold launch's first read): nothing is learned from that, so the
    /// stored record is returned untouched, never forgotten and never newly dated.
    @discardableResult
    static func observe(hidden: Int?, bank: String, now: Date = Date(), defaults: UserDefaults = .standard) -> Record? {
        guard let hidden else { return load(bank: bank, defaults: defaults) }
        guard hidden > 0 else {
            if load(bank: bank, defaults: defaults) != nil { save(nil, bank: bank, defaults: defaults) }
            return nil
        }
        if let held = load(bank: bank, defaults: defaults) { return held }
        let fresh = Record(since: now, dismissed: false)
        save(fresh, bank: bank, defaults: defaults)
        return fresh
    }

    static func dismiss(bank: String, defaults: UserDefaults = .standard) {
        guard var held = load(bank: bank, defaults: defaults) else { return }
        held.dismissed = true
        save(held, bank: bank, defaults: defaults)
    }

    /// The line, or nil when nothing is hidden, it was dismissed, or the month is over.
    static func line(hidden: Int, record: Record?, now: Date = Date(), locale: Locale = .autoupdatingCurrent) -> String? {
        guard hidden > 0, let record, !record.dismissed else { return nil }
        let age = now.timeIntervalSince(record.since)
        guard age < Double(showForDays) * 86_400 else { return nil }
        let day = record.since.formatted(Date.FormatStyle(locale: locale).day().month(.abbreviated))
        return Copy.Keep.moved(hidden, since: day, locale: locale)
    }
}
