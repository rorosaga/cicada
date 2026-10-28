import Foundation
import SwiftUI

/// Discriminator for a unified inbox item. Matches `InboxKind` in
/// `api/models/schemas.py` (wire values are snake_case for `merge_suggestion`).
enum InboxKind: String, Codable {
    case decay, conflict, clarification
    case mergeSuggestion = "merge_suggestion"
    // G113 slice 3: Sleep has written both kinds for months
    // (`inbox_generator.py`'s `divergence_nudge`/`normalization_audit`
    // branches); the API only just started decoding them (`InboxKind` in
    // `api/models/schemas.py`) instead of dropping the item and warning.
    case divergence
    case normalization
    // G129 slice 2: a bookmark removed from the browser — keep it or archive
    // the media entity it named.
    case removal
    // G141 PJ-6: a quiet thread or a passed milestone — "How did it go?".
    // Sleep's tail writes it; before this case it decoded as `.unknown` and
    // wore the "Update available" label, which reads as a software update.
    case followup
    // G198: an agent's change to a page's words or aliases, waiting for the person (the agent is not on their list
    // of agents that edit pages directly). Options `apply` / `dismiss` come from the server; `body` previews it.
    case pageEdit = "page_edit"
    // G205: an agent asking the person to do something only they can (today: sign in to a site so it can read a page).
    // Drawn as a small card above the questions, never as a question row; sent as a Mac notification once.
    case agentRequest = "agent_request"
    // Forward-compat fallback (matches `EntityType`/`Epistemic`/`SourceTrust`'s
    // existing pattern in this codebase). Before this, an unrecognized raw
    // value threw `DecodingError.dataCorrupted` out of `InboxItem.init(from:)`,
    // which propagates out of `[InboxItem]`'s array decode and drops EVERY
    // pending item, not just the one this build has never heard of — `removal`
    // is what exposed the gap, but any future kind hits the same failure
    // without this case.
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = InboxKind(rawValue: raw) ?? .unknown
    }

    /// A kind in a person's words (inbox v2, owner 2026-10-26: "I don't really get … possible duplicates and stuff"):
    /// the tabs, the glyph's help and VoiceOver. "Decay", "Clarification", "Divergence" and "Predicate fold" were the
    /// pipeline's names; the wire values above never change.
    var label: String {
        switch self {
        case .decay: "Fading"
        case .conflict: "Conflict"
        case .clarification: "Question"
        case .mergeSuggestion: "Possible duplicate"
        case .divergence: "Disagreement"
        case .normalization: "Wording"
        case .removal: "Removed bookmark"
        case .followup: "Follow-up"
        case .pageEdit: "Page edit"
        case .agentRequest: "Agent request"
        case .unknown: "Update available"
        }
    }

    /// The heading of a kind's group in the Inbox (inbox v2): what the questions under it are, plural.
    var groupTitle: String {
        switch self {
        case .decay: "Fading pages"
        case .conflict: "Conflicts"
        case .clarification: "Questions"
        case .mergeSuggestion: "Possible duplicates"
        case .divergence: "Disagreements with an agent"
        case .normalization: "Wording to check"
        case .removal: "Removed bookmarks"
        case .followup: "Follow-ups"
        case .pageEdit: "Proposed page edits"
        case .agentRequest: "Agent requests"
        case .unknown: "Other questions"
        }
    }

    /// Leading-icon SF Symbol per kind.
    var icon: String {
        switch self {
        case .decay: "clock.arrow.circlepath"
        case .conflict: "exclamationmark.triangle"
        case .clarification: "questionmark.circle"
        case .mergeSuggestion: "arrow.triangle.merge"
        case .divergence: "arrow.triangle.branch"
        case .normalization: "arrow.triangle.merge"
        case .removal: "bookmark.slash"
        case .followup: "arrow.uturn.backward.circle"
        case .pageEdit: "pencil"
        case .agentRequest: "person.crop.circle.badge.questionmark"
        case .unknown: "questionmark.circle"
        }
    }

    var color: Color { CicadaTheme.inboxColor(for: self) }
}

/// What input the card's action row needs. Matches `RequiredInput` in the API.
enum RequiredInput: String, Codable {
    case none, choice, freetext, merge
}

/// One answerable option on an inbox question. Matches `InboxOption` in
/// `api/models/schemas.py`. `ageDays` is derived server-side at read time.
/// G115 Phase 1: `recommended` marks the ONE option Sleep proposed (the key the
/// ledger's `_verdict` grades `agreed`); `verdict` is on the wire for agents and
/// tests and is never rendered as copy.
struct InboxOption: Identifiable, Hashable {
    var key: String
    var label: String
    var description: String?
    var claimId: String?
    var observedAt: String?
    var lastReferenced: String?
    var ageDays: Int?
    var recommended: Bool = false
    var verdict: String? = nil

    var id: String { key }

    /// DR-58 / R-DI12 — the option's age as a `Tag`: "today", "5d", "3w", "6mo", "2y". One rule
    /// with the row's age (`InboxAge.compact`), whose boundaries and half-even rounding are
    /// `phrase(days:)`'s, so "3w" on the tag and "3 weeks ago" in the description never disagree
    /// (the old capsule rounded half away from zero and could). `nil` when the option has no claim
    /// behind it (the synthetic rows).
    var ageCapsule: String? { ageDays.map(InboxAge.compact(days:)) }
}

// `Codable` is declared in an EXTENSION on purpose: a custom `init(from:)` in
// the struct body would suppress the memberwise initialiser, and
// `InboxItem.init(from:)`'s legacy flat-`[String]` branch calls it with seven
// labelled arguments. In an extension the memberwise init survives, and
// `recommended`/`verdict` — `var`s with defaults, declared last — are simply
// omitted by that call.
extension InboxOption: Codable {
    enum CodingKeys: String, CodingKey {
        case key, label, description, claimId, observedAt, lastReferenced, ageDays, recommended, verdict
    }

    /// Tolerant on purpose: a `SnapshotCache` payload written before G115 has
    /// no `recommended`/`verdict`, and a synthesized decoder would refuse the
    /// whole inbox over one missing key.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        description = try c.decodeIfPresent(String.self, forKey: .description)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        observedAt = try c.decodeIfPresent(String.self, forKey: .observedAt)
        lastReferenced = try c.decodeIfPresent(String.self, forKey: .lastReferenced)
        ageDays = try c.decodeIfPresent(Int.self, forKey: .ageDays)
        recommended = try c.decodeIfPresent(Bool.self, forKey: .recommended) ?? false
        verdict = try c.decodeIfPresent(String.self, forKey: .verdict)
    }
}

/// Why an item exists (G97): the conversation and sentence that raised it,
/// resolved server-side at read. `mentionOffsets` index the EXCERPT as
/// Unicode-scalar offsets (Python `str` indices); `start`/`end` are the
/// EXCERPT WINDOW's absolute offsets into the episode body
/// (`inbox_context.excerpt_around` — G118 slice 2 corrected this comment,
/// which used to call them the mention's), so the mention itself sits at
/// `start + mentionOffsets[0]` (R-PB16). `tier == "none"` carries the literal
/// `[ no source recorded ]` in `excerpt` — shown, never hidden.
struct InboxCause: Codable, Hashable {
    var episodeId: String?
    var timestamp: String?
    var conversationId: String?
    var harness: String?
    var origin: String?
    var conversationTitle: String?
    var excerpt: String = ""
    var mentionOffsets: [[Int]] = []
    var start: Int?
    var end: Int?
    var tier: String = "none"
    var spanKind: String = "derived"

    enum CodingKeys: String, CodingKey {
        case episodeId, timestamp, conversationId, harness, origin, conversationTitle
        case excerpt, mentionOffsets, start, end, tier, spanKind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        conversationTitle = try c.decodeIfPresent(String.self, forKey: .conversationTitle)
        excerpt = try c.decodeIfPresent(String.self, forKey: .excerpt) ?? ""
        mentionOffsets = try c.decodeIfPresent([[Int]].self, forKey: .mentionOffsets) ?? []
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        tier = try c.decodeIfPresent(String.self, forKey: .tier) ?? "none"
        spanKind = try c.decodeIfPresent(String.self, forKey: .spanKind) ?? "derived"
    }
}

/// One unified inbox item. Decodes the camelCase payload from `GET /inbox`
/// (`api/routers/inbox.py` → `InboxItem`). `options` decodes both the current
/// object form and the legacy flat `[String]`, so an item written before G60
/// still renders.
/// G61 S3 — one agent report on an inbox question (`InboxItem.checks`). The quote is the page's words as the agent
/// reported them; `checker` is a harness label, never a model.
struct InboxCheckFinding: Codable, Equatable {
    var at: String
    var checker: String
    var checkerKind: String?
    var host: String
    var ref: String?
    var outcome: String
    var optionKey: String?
    var proposedValue: String?
    var quote: String?
}

/// The quick review's page context (`InboxSubject` in `api/models/schemas.py`): the page's lead sentence, how many
/// dated conversations said it, and the latest of their days.
struct InboxSubject: Codable, Equatable {
    var summary: String?
    var conversations: Int
    var lastSaid: String?

    init(summary: String? = nil, conversations: Int = 0, lastSaid: String? = nil) {
        self.summary = summary
        self.conversations = conversations
        self.lastSaid = lastSaid
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
        lastSaid = try c.decodeIfPresent(String.self, forKey: .lastSaid)
    }
}

/// A predicate fold in words (`InboxFold`): the label as said, the predicate it was filed under, what it covers.
struct InboxFold: Codable, Equatable {
    var raw: String
    var canonical: String
    var claims: Int
    var pages: Int
    var example: String?

    init(raw: String, canonical: String, claims: Int = 0, pages: Int = 0, example: String? = nil) {
        self.raw = raw
        self.canonical = canonical
        self.claims = claims
        self.pages = pages
        self.example = example
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        raw = try c.decode(String.self, forKey: .raw)
        canonical = try c.decode(String.self, forKey: .canonical)
        claims = try c.decodeIfPresent(Int.self, forKey: .claims) ?? 0
        pages = try c.decodeIfPresent(Int.self, forKey: .pages) ?? 0
        example = try c.decodeIfPresent(String.self, forKey: .example)
    }
}

/// G205 — what an agent asks of the person (`InboxItem.request`, `agent_requests.py`): the agent by catalog id and
/// name, its umbrella's logo slug, the site, its reason, and the notification's ready-made words.
struct AgentRequestInfo: Codable, Equatable {
    struct Notification: Codable, Equatable {
        var title: String
        var body: String
        var openUrl: String?
    }

    var agent: String
    var agentName: String
    var umbrella: String?
    var logo: String?
    var site: String?
    var reason: String?
    var notification: Notification?

    init(agent: String, agentName: String, umbrella: String? = nil, logo: String? = nil, site: String? = nil,
         reason: String? = nil, notification: Notification? = nil) {
        self.agent = agent; self.agentName = agentName; self.umbrella = umbrella; self.logo = logo
        self.site = site; self.reason = reason; self.notification = notification
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agent = try c.decodeIfPresent(String.self, forKey: .agent) ?? "other"
        agentName = try c.decodeIfPresent(String.self, forKey: .agentName) ?? ""
        umbrella = try c.decodeIfPresent(String.self, forKey: .umbrella)
        logo = try c.decodeIfPresent(String.self, forKey: .logo)
        site = try c.decodeIfPresent(String.self, forKey: .site)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        notification = try? c.decodeIfPresent(Notification.self, forKey: .notification)
    }
}

/// G61 "Where to check" (ruling 36 D5, #422) — one waiting link of the grouped review (`asks: "sources"`): its page,
/// the link, what kind of link it is, who added it and where it was found (offsets, never a copy).
struct WhereToCheckRow: Codable, Equatable, Identifiable {
    struct Evidence: Codable, Equatable {
        var episode: String?
        var start: Int?
        var end: Int?
        var kind: String?
        var page: Bool?
    }

    var id: String
    var page: String
    var pageName: String
    var pageType: String
    var ref: String
    var predicate: String
    var linkKind: String
    var label: String
    var addedBy: String
    var evidence: Evidence?

    init(id: String, page: String, pageName: String = "", pageType: String = "", ref: String, predicate: String = "",
         linkKind: String = "website", label: String = "", addedBy: String = "", evidence: Evidence? = nil) {
        self.id = id; self.page = page; self.pageName = pageName; self.pageType = pageType; self.ref = ref
        self.predicate = predicate; self.linkKind = linkKind; self.label = label; self.addedBy = addedBy
        self.evidence = evidence
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        page = try c.decode(String.self, forKey: .page)
        pageName = try c.decodeIfPresent(String.self, forKey: .pageName) ?? ""
        pageType = try c.decodeIfPresent(String.self, forKey: .pageType) ?? ""
        ref = try c.decode(String.self, forKey: .ref)
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate) ?? ""
        linkKind = try c.decodeIfPresent(String.self, forKey: .linkKind) ?? "website"
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        addedBy = try c.decodeIfPresent(String.self, forKey: .addedBy) ?? ""
        evidence = try? c.decodeIfPresent(Evidence.self, forKey: .evidence)
    }
}

/// Decodes to nil instead of throwing, so one unreadable element never loses its siblings.
private struct Lenient<T: Codable>: Codable {
    let value: T?
    init(from decoder: Decoder) throws { value = try? T(from: decoder) }
    func encode(to encoder: Encoder) throws { try value?.encode(to: encoder) }
}

struct InboxItem: Identifiable, Codable {
    let id: String
    var kind: InboxKind
    var requiredInput: RequiredInput
    var status: String
    var priority: Double
    var entityId: String
    var entityName: String
    var title: String
    var body: String
    var options: [InboxOption]
    var createdDate: String
    // G60 question object
    var question: String?
    var allowOther: Bool
    var allowDefer: Bool
    var predicate: String?
    var hint: String?
    // G129 slice 2 — which browser channel (`chrome-bookmarks`/
    // `safari-bookmarks`) proposed a `removal` item; nil for every other kind.
    var channel: String?
    var remindAfter: String?
    var updatedDate: String?
    // clarification / merge extras
    var uncertaintyType: String?
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var mergeTargetHint: String?
    /// A clarification that asks for a person's name (`"name"`, the backend's `role_people`): the card draws a name
    /// field and "I'd rather not say" (`NameBody`). Optional, so an older cache still decodes.
    var asks: String?
    // G115 Phase 1 — every one optional so a pre-G115 cache still decodes.
    var entityType: String?
    var sourceEpisode: String?
    var sourceEpisodeTimestamp: String?
    var claimId: String?
    var cause: InboxCause?
    var extractorConfidence: Double?
    var extractorModel: String?
    var recommendedKey: String?
    /// G98: a conflict on a multi-valued predicate — shown, never asked.
    var informational: Bool
    /// G61 S3 — what an agent reported after looking at a source for this question, newest first. A report only: it
    /// settles nothing, highlights nothing and reorders nothing.
    var checks: [InboxCheckFinding]
    /// The quick review (owner 2026-10-19), decay and fold cards only: what the page is and how often it was said,
    /// and a fold's two names. Derived by the server at read; optional, so an older server or cache still decodes.
    var subject: InboxSubject? = nil
    var fold: InboxFold? = nil
    /// G205 — an `agent_request`'s agent, site, reason and notification words. Lenient; nil on every other kind.
    var request: AgentRequestInfo? = nil
    /// G61 "Where to check" — the links waiting (`asks: "sources"`), and whether this is the ONE grouped review.
    var rows: [WhereToCheckRow]? = nil
    var review: Bool = false
    /// Ruling 48 (1) — the question as a person would ask it and its reason (`inbox_wording`, derived at read). Home's
    /// rows, a page's questions strip and the catch-up chat say these; nil from an older server or cache.
    var spokenQuestion: String? = nil
    var spokenReason: String? = nil

    enum CodingKeys: String, CodingKey {
        case id, kind, requiredInput, status, priority
        case entityId, entityName, title, body, options, createdDate
        case question, allowOther, allowDefer, predicate, hint, channel, remindAfter, updatedDate
        case uncertaintyType, suggestedClassification, suggestedConfidence, mergeTargetHint, asks
        case entityType, sourceEpisode, sourceEpisodeTimestamp, claimId, cause
        case extractorConfidence, extractorModel, recommendedKey, informational, checks
        case subject, fold, request, rows, review, spokenQuestion, spokenReason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(InboxKind.self, forKey: .kind)
        requiredInput = try c.decode(RequiredInput.self, forKey: .requiredInput)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "pending"
        priority = try c.decodeIfPresent(Double.self, forKey: .priority) ?? 0
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        title = try c.decode(String.self, forKey: .title)
        body = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
        // Object form first; a server or cached payload from before G60 hands
        // back `["A","B"]`, which becomes positionally-keyed options.
        if let objects = try? c.decodeIfPresent([InboxOption].self, forKey: .options) {
            options = objects ?? []
        } else if let labels = try c.decodeIfPresent([String].self, forKey: .options) {
            options = labels.enumerated().map {
                InboxOption(key: "\($0.offset)", label: $0.element, description: nil,
                            claimId: nil, observedAt: nil, lastReferenced: nil, ageDays: nil)
            }
        } else {
            options = []
        }
        createdDate = try c.decodeIfPresent(String.self, forKey: .createdDate) ?? ""
        question = try c.decodeIfPresent(String.self, forKey: .question)
        allowOther = try c.decodeIfPresent(Bool.self, forKey: .allowOther) ?? false
        allowDefer = try c.decodeIfPresent(Bool.self, forKey: .allowDefer) ?? false
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate)
        hint = try c.decodeIfPresent(String.self, forKey: .hint)
        channel = try c.decodeIfPresent(String.self, forKey: .channel)
        remindAfter = try c.decodeIfPresent(String.self, forKey: .remindAfter)
        updatedDate = try c.decodeIfPresent(String.self, forKey: .updatedDate)
        uncertaintyType = try c.decodeIfPresent(String.self, forKey: .uncertaintyType)
        suggestedClassification = try c.decodeIfPresent(String.self, forKey: .suggestedClassification)
        suggestedConfidence = try c.decodeIfPresent(Double.self, forKey: .suggestedConfidence)
        mergeTargetHint = try c.decodeIfPresent(String.self, forKey: .mergeTargetHint)
        asks = try c.decodeIfPresent(String.self, forKey: .asks)
        entityType = try c.decodeIfPresent(String.self, forKey: .entityType)
        sourceEpisode = try c.decodeIfPresent(String.self, forKey: .sourceEpisode)
        sourceEpisodeTimestamp = try c.decodeIfPresent(String.self, forKey: .sourceEpisodeTimestamp)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        cause = try c.decodeIfPresent(InboxCause.self, forKey: .cause)
        extractorConfidence = try c.decodeIfPresent(Double.self, forKey: .extractorConfidence)
        extractorModel = try c.decodeIfPresent(String.self, forKey: .extractorModel)
        recommendedKey = try c.decodeIfPresent(String.self, forKey: .recommendedKey)
        informational = try c.decodeIfPresent(Bool.self, forKey: .informational) ?? false
        // Lenient: one finding this build cannot read is dropped alone, never the card.
        checks = ((try? c.decodeIfPresent([Lenient<InboxCheckFinding>].self, forKey: .checks)) ?? nil)?
            .compactMap(\.value) ?? []
        // Lenient like `checks`: a review field this build cannot read costs the field, never the card.
        subject = (try? c.decodeIfPresent(InboxSubject.self, forKey: .subject)) ?? nil
        fold = (try? c.decodeIfPresent(InboxFold.self, forKey: .fold)) ?? nil
        request = (try? c.decodeIfPresent(AgentRequestInfo.self, forKey: .request)) ?? nil
        rows = ((try? c.decodeIfPresent([Lenient<WhereToCheckRow>].self, forKey: .rows)) ?? nil)?.compactMap(\.value)
        review = (try? c.decodeIfPresent(Bool.self, forKey: .review)) ?? false
        spokenQuestion = (try? c.decodeIfPresent(String.self, forKey: .spokenQuestion)) ?? nil
        spokenReason = (try? c.decodeIfPresent(String.self, forKey: .spokenReason)) ?? nil
    }

    /// G61 — the one grouped "Confirm N links" review, drawn as its own card above the questions.
    var isWhereToCheckReview: Bool { asks == "sources" && review && !(rows ?? []).isEmpty }
    /// Drawn above the questions, never as a question row (G205 agent requests, the G61 grouped review).
    var isTopCard: Bool { kind == .agentRequest || isWhereToCheckReview }

    /// Display name for the card header, falling back to the title when no
    /// entity name is attached (pure clarification with no entity yet).
    var displayName: String {
        entityName.isEmpty ? title : entityName
    }

    /// What the focus card shows as its H1, and a row as its question.
    var questionText: String {
        if let question, !question.isEmpty { return question }
        return title.isEmpty ? body : title
    }

    /// Ruling 48 (1) — what Home, a page's strip and the catch-up say: the plain question, else the stored one.
    var askText: String {
        if let spokenQuestion, !spokenQuestion.isEmpty { return spokenQuestion }
        return questionText
    }

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}

extension InboxItem {
    /// Open `removal` items proposed against one browser channel (G129 slice
    /// 2) — pure so `ChannelSourceView`'s Deletions subsection is testable
    /// without a view, same pattern as `SourceOverview.ownedItems`.
    static func openRemovals(in items: [InboxItem], channelId: String) -> [InboxItem] {
        items.filter { $0.kind == .removal && $0.channel == channelId }
    }
}

extension InboxCause {
    /// Where "Show in conversation" opens (G118 slice 2, design §4.7, R-PB16):
    /// the mention's absolute offsets, asked for with NO hash — the cause is
    /// recomputed at every read, so it is current by construction. A cause
    /// found by name (`spanKind == "derived"`) stays labelled derived in the
    /// Reader; an asserted G118 span lands washed. A cause with no mention
    /// opens its conversation at the top; tier `none` has nothing to open.
    func readerTarget(subjectId: String?) -> ReaderTarget? {
        guard tier != "none", let episodeId, !episodeId.isEmpty else { return nil }
        if let start, let pair = mentionOffsets.first, pair.count == 2, pair[0] >= 0, pair[1] > pair[0] {
            return ReaderTarget(episode: episodeId,
                                focus: .span(start: start + pair[0], end: start + pair[1], hash: nil,
                                             derived: spanKind != "asserted"),
                                subjectId: subjectId, knownTitle: conversationTitle, knownHarness: harness)
        }
        return ReaderTarget(episode: episodeId, subjectId: subjectId, knownTitle: conversationTitle,
                            knownHarness: harness)
    }
}
