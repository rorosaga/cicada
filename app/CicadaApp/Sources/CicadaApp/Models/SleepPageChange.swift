import Foundation

/// `GET /sleep/runs/{id}/pages/{page}/change` and `GET /sleep/history/{commit}/pages/{page}/change` (items-6, owner
/// 2026-11-24: "pages render normally, not as raw markdown … and I don't get why a page was modified, what influenced
/// this change?"): one page's change in one consolidation, computed by the backend and ready to draw — why it changed
/// (the conversations of the run that fed it, or the step), its facts as sentences with what moved in each, its prose
/// as the page's own markdown in blocks, and the few other things that moved. No file diff, no claim id, no
/// bookkeeping key is ever on this wire. Lenient like every Sleep type: a missing or mistyped part is empty, never a
/// failed decode.
struct SleepPageChange: Codable, Equatable {
    /// One conversation of the run that fed the page (the opened card's own row, plus `inRun`).
    struct Conversation: Codable, Equatable, Identifiable {
        var conversation: SleepConsolidated.Conversation
        /// False for a conversation outside this run that a fact's own evidence names.
        var inRun: Bool

        var id: String { conversation.id }

        init(_ conversation: SleepConsolidated.Conversation, inRun: Bool = true) {
            self.conversation = conversation; self.inRun = inRun
        }

        init(from decoder: Decoder) throws {
            conversation = try SleepConsolidated.Conversation(from: decoder)
            let c = try decoder.container(keyedBy: Keys.self)
            inRun = ((try? c.decodeIfPresent(Bool.self, forKey: .inRun)) ?? nil) ?? true
        }

        func encode(to encoder: Encoder) throws {
            try conversation.encode(to: encoder)
            var c = encoder.container(keyedBy: Keys.self)
            try c.encode(inRun, forKey: .inRun)
        }

        private enum Keys: String, CodingKey { case inRun }
    }

    /// What moved in one field of a fact or of the page. `before` / `after` are words as the wire has them (a date, a
    /// confidence as "0.8"); `added` / `removed` carry a list field's members (an alias, a conversation id).
    struct FieldChange: Codable, Equatable {
        var field: String
        var before: String?
        var after: String?
        var added: [String] = []
        var removed: [String] = []

        init(field: String, before: String? = nil, after: String? = nil, added: [String] = [], removed: [String] = []) {
            self.field = field; self.before = before; self.after = after; self.added = added; self.removed = removed
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            field = ((try? c.decodeIfPresent(String.self, forKey: .field)) ?? nil) ?? "details"
            before = (try? c.decodeIfPresent(String.self, forKey: .before)) ?? nil
            after = (try? c.decodeIfPresent(String.self, forKey: .after)) ?? nil
            added = ((try? c.decodeIfPresent([String].self, forKey: .added)) ?? nil) ?? []
            removed = ((try? c.decodeIfPresent([String].self, forKey: .removed)) ?? nil) ?? []
        }
    }

    /// One fact: the one claim wire (its NEW state, or its last for a withdrawn fact), what moved, and the
    /// conversation its own evidence names (with `inRun` saying whether it is one of this run's).
    struct Fact: Codable, Equatable, Identifiable {
        var claim: Claim
        var changes: [FieldChange] = []
        var conversation: String?
        var inRun: Bool = false

        var id: String { claim.id }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            claim = try c.decode(Claim.self, forKey: .claim)
            changes = ((try? c.decodeIfPresent(LossyArray<FieldChange>.self, forKey: .changes)) ?? nil)?.items ?? []
            conversation = (try? c.decodeIfPresent(String.self, forKey: .conversation)) ?? nil
            inRun = ((try? c.decodeIfPresent(Bool.self, forKey: .inRun)) ?? nil) ?? false
        }
    }

    struct Facts: Codable, Equatable {
        var added: [Fact] = []
        var withdrawn: [Fact] = []
        var changed: [Fact] = []
        /// Facts whose confidence alone moved (silence): counted, never listed.
        var faded: Int = 0
        var truncated: Bool = false
        /// The whole counts (`added`, `withdrawn`, `changed`) even when a list was cut.
        var counts: [String: Int] = [:]

        var isEmpty: Bool { added.isEmpty && withdrawn.isEmpty && changed.isEmpty }

        init() {}

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            func facts(_ key: CodingKeys) -> [Fact] { ((try? c.decodeIfPresent(LossyArray<Fact>.self, forKey: key)) ?? nil)?.items ?? [] }
            added = facts(.added); withdrawn = facts(.withdrawn); changed = facts(.changed)
            faded = ((try? c.decodeIfPresent(Int.self, forKey: .faded)) ?? nil) ?? 0
            truncated = ((try? c.decodeIfPresent(Bool.self, forKey: .truncated)) ?? nil) ?? false
            counts = ((try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? nil) ?? [:]
        }
    }

    /// One piece of an edited paragraph: `equal` plus `removed` is the old text, `equal` plus `added` the new.
    struct Segment: Codable, Equatable {
        enum Op: String, Codable, Equatable { case equal, added, removed }
        var op: Op
        var text: String

        init(_ op: Op, _ text: String) { self.op = op; self.text = text }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            op = ((try? c.decodeIfPresent(Op.self, forKey: .op)) ?? nil) ?? .equal
            text = ((try? c.decodeIfPresent(String.self, forKey: .text)) ?? nil) ?? ""
        }
    }

    /// One block of the page's prose as the page writes it.
    struct Block: Codable, Equatable {
        enum Op: String, Codable, Equatable { case context, added, removed, edited }
        var op: Op
        /// The block's own markdown (the new text for an edited one).
        var markdown: String
        /// The heading text the block sits under (inline markdown); nil on a heading block itself.
        var heading: String?
        /// A heading block's own level; 0 for any other block.
        var level: Int = 0
        var segments: [Segment] = []

        init(op: Op, markdown: String, heading: String? = nil, level: Int = 0, segments: [Segment] = []) {
            self.op = op; self.markdown = markdown; self.heading = heading; self.level = level; self.segments = segments
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            op = ((try? c.decodeIfPresent(Op.self, forKey: .op)) ?? nil) ?? .context
            markdown = ((try? c.decodeIfPresent(String.self, forKey: .markdown)) ?? nil) ?? ""
            heading = (try? c.decodeIfPresent(String.self, forKey: .heading)) ?? nil
            level = ((try? c.decodeIfPresent(Int.self, forKey: .level)) ?? nil) ?? 0
            segments = ((try? c.decodeIfPresent(LossyArray<Segment>.self, forKey: .segments)) ?? nil)?.items ?? []
        }

        private enum CodingKeys: String, CodingKey { case op, markdown, heading, level, segments }
    }

    struct Prose: Codable, Equatable {
        var blocks: [Block] = []
        var counts: [String: Int] = [:]
        var truncated: Bool = false

        /// Whether any block is a change (a block of context alone is nothing to show).
        var hasChange: Bool { blocks.contains { $0.op != .context } }

        init() {}

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            blocks = ((try? c.decodeIfPresent(LossyArray<Block>.self, forKey: .blocks)) ?? nil)?.items ?? []
            counts = ((try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? nil) ?? [:]
            truncated = ((try? c.decodeIfPresent(Bool.self, forKey: .truncated)) ?? nil) ?? false
        }
    }

    /// `created`, `updated`, `archived`, `removed`; `faded` and `bookkeeping` when asked for by id (the page then
    /// has `empty` and nothing else).
    var change: String
    var page: SleepConsolidated.Page
    var conversations: [Conversation] = []
    var facts: Facts = Facts()
    var prose: Prose = Prose()
    var other: [FieldChange] = []
    /// Smaller details of the page's record that have no sentence of their own (a count, not a list).
    var otherDetails: Int = 0
    /// Nothing in substance changed in the page's net before-versus-after (a restored page, a faded one).
    var empty: Bool = false
    var truncated: Bool = false

    init(change: String, page: SleepConsolidated.Page, conversations: [Conversation] = [], facts: Facts = Facts(),
         prose: Prose = Prose(), other: [FieldChange] = [], otherDetails: Int = 0, empty: Bool = false,
         truncated: Bool = false) {
        self.change = change; self.page = page; self.conversations = conversations; self.facts = facts
        self.prose = prose; self.other = other; self.otherDetails = otherDetails; self.empty = empty
        self.truncated = truncated
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        page = try c.decode(SleepConsolidated.Page.self, forKey: .page)
        change = ((try? c.decodeIfPresent(String.self, forKey: .change)) ?? nil) ?? page.change?.rawValue ?? "updated"
        conversations = ((try? c.decodeIfPresent(LossyArray<Conversation>.self, forKey: .conversations)) ?? nil)?.items ?? []
        facts = ((try? c.decodeIfPresent(Facts.self, forKey: .facts)) ?? nil) ?? Facts()
        prose = ((try? c.decodeIfPresent(Prose.self, forKey: .prose)) ?? nil) ?? Prose()
        other = ((try? c.decodeIfPresent(LossyArray<FieldChange>.self, forKey: .other)) ?? nil)?.items ?? []
        otherDetails = ((try? c.decodeIfPresent(Int.self, forKey: .otherDetails)) ?? nil) ?? 0
        empty = ((try? c.decodeIfPresent(Bool.self, forKey: .empty)) ?? nil) ?? false
        truncated = ((try? c.decodeIfPresent(Bool.self, forKey: .truncated)) ?? nil) ?? false
    }

    private enum CodingKeys: String, CodingKey {
        case change, page, conversations, facts, prose, other, otherDetails, empty, truncated
    }

    /// Whether anything of substance is on it to draw: a fact, a changed block of prose, or another change.
    var hasContent: Bool { !facts.isEmpty || prose.hasChange || !other.isEmpty || otherDetails > 0 }

    /// The conversation a fact's evidence names, from the wire's list.
    func conversation(_ id: String?) -> SleepConsolidated.Conversation? {
        guard let id else { return nil }
        return conversations.first { $0.id == id }?.conversation
    }

    /// The path of this page's change under a consolidation.
    static func path(_ key: SleepConsolidatedKey, page: String) -> String {
        let encoded = page.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? page
        switch key {
        case .run(let id):
            return "/sleep/runs/\(id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id)/pages/\(encoded)/change"
        case .commit(let hash):
            return "/sleep/history/\(hash.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? hash)/pages/\(encoded)/change"
        }
    }
}

/// An array that drops an element it cannot decode instead of failing the whole list.
struct LossyArray<Element: Codable & Equatable>: Codable, Equatable {
    var items: [Element]

    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        var out: [Element] = []
        while !container.isAtEnd {
            if let item = try? container.decode(Element.self) { out.append(item) } else { _ = try? container.decode(DiscardedValue.self) }
        }
        items = out
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        for item in items { try container.encode(item) }
    }

    private struct DiscardedValue: Decodable {}
}
