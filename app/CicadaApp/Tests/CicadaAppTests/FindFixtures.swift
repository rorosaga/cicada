import Foundation
@testable import CicadaApp

/// Synthetic rows for the G136 palette tests — placeholders only
/// (alpha-project, bob-example, beta-bank, example.com), never a bank.
enum FindFixtures {
    static func node(_ id: String, _ name: String, type: EntityType = .project, tags: [String] = [],
                     summary: String? = nil, degree: Int = 0, isHub: Bool = false,
                     isFacet: Bool = false) -> GraphNode {
        GraphNode(id: id, name: name, type: type, tags: tags, degree: degree, isHub: isHub,
                  isFacet: isFacet, summary: summary)
    }

    static func media(_ entity: String, title: String, url: String = "https://example.com/a",
                      site: String? = nil, description: String? = nil, origin: String? = nil,
                      savedAt: String = "2026-09-01") -> MediaFeedItem {
        var object: [String: Any] = ["mediaEntityId": entity, "url": url, "title": title,
                                     "mediaType": "bookmark", "savedAt": savedAt,
                                     "tags": [String](), "relevance": 0.5]
        if let site { object["site"] = site }
        if let description { object["description"] = description }
        if let origin { object["origin"] = origin }
        return try! JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    static func inbox(_ id: String, question: String, entityName: String = "", excerpt: String = "",
                      kind: String = "clarification", priority: Double = 0.5) -> InboxItem {
        let object: [String: Any] = ["id": id, "kind": kind, "requiredInput": "choice", "title": question,
                                     "question": question, "entityName": entityName, "priority": priority,
                                     "cause": ["excerpt": excerpt]]
        return try! JSONDecoder().decode(InboxItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    static func bank(_ name: String) -> MemoryBank {
        try! JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name": "\#(name)"}"#.utf8))
    }

    static func inputs() -> QuickIndexInputs {
        var inputs = QuickIndexInputs()
        inputs.nodes = [
            node("alpha-project", "alpha-project", tags: ["robotics"], summary: "A research project about retrieval.", degree: 5),
            node("bob-example", "bob-example", type: .person, degree: 2),
            node("hub:project", "Alpha Hub", type: .hub, isHub: true),
            node("alpha-project#work", "alpha-project", isFacet: true),
            node("media-alpha", "Alpha paper notes", type: .media),
        ]
        inputs.media = [
            media("media-alpha", title: "Alpha paper notes", site: "example.com"),
            media("media-alpha", title: "Alpha paper notes", url: "https://example.com/b"),
        ]
        inputs.sources = [SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness,
                                         mark: "claude-code", episodes: 12, harness: "claude-code")]
        inputs.inbox = [inbox("inbox-001", question: "Still tracking alpha-project?", entityName: "alpha-project",
                              excerpt: "we paused alpha-project in June")]
        inputs.banks = [bank("default"), bank("beta-bank")]
        inputs.activeBank = "default"
        inputs.unprocessed = 3
        return inputs
    }
}
