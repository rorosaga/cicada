import Foundation
@testable import CicadaApp

/// A synthetic page shaped like the owner page of a bank imported from a few years of chat exports (placeholder names
/// only): 3,500 claims in one ```claims fence (≈2.5 MB of markdown), ~2,000 characters of merged prose, a provenance
/// with the 50 shown conversations, and a graph of 2,000 pages and ~5,000 edges around it.
enum OwnerScaleFixture {
    static let ownerId = "owner-example"
    static let claimCount = 3_500
    static let pageCount = 2_000

    static let pages: [String] = (0..<pageCount).map { String(format: "thing-%04d", $0) }

    static let claims: [Claim] = {
        let predicates = ["works-on", "uses", "knows", "interested-in", "prefers", "lives-in"]
        let observers = ["agent", "owner-example", "external"]
        var rows: [String] = []
        for i in 0..<claimCount {
            let day = String(format: "202%d-%02d-%02d", 3 + i % 4, 1 + i % 12, 1 + i % 28)
            let episode = "ep_\(day)_\(String(format: "%03d", i % 50))"
            let superseded = i % 9 == 0 ? #","validTo":"\#(day)","supersededBy":"clm_\#(i + 1)""# : ""
            rows.append(#"""
            {"id":"clm_\#(i)","text":"Owner Example \#(predicates[i % 6]) [[\#(pages[(i * 7) % pageCount])]] — a sentence merged from several conversations","subject":"owner-example","predicate":"\#(predicates[i % 6])","object":"\#(pages[(i * 7) % pageCount])","context":"general","observer":"\#(observers[i % 3])","validFrom":"\#(day)","recordedAt":"\#(day)","authoredBy":"cicada","evidence":[{"episode":"\#(episode)","start":6,"end":40,"kind":"user","hash":"abc"}]\#(superseded)}
            """#)
        }
        let data = Data(("[" + rows.joined(separator: ",") + "]").utf8)
        return (try? JSONDecoder().decode([Claim].self, from: data)) ?? []
    }()

    static let prose = "## Summary\nThe owner of this memory.\n\n## Key Facts\n"
        + String(repeating: "A merged sentence about the owner from many conversations. ", count: 34) + "\n"

    /// The page body as `markdownContent` carries it: the prose, then the whole fence.
    static let markdown: String = {
        var fence = "```claims\n"
        for i in 0..<claimCount {
            fence += """
            - id: clm_\(i)
              text: Owner Example uses thing \(i) — a sentence merged from several conversations
              subject: owner-example
              predicate: uses
              object: \(pages[(i * 7) % pageCount])
              context: general
              observer: agent
              valid_from: '2024-01-01'
              recorded_at: '2024-01-01'
              authored_by: cicada
              evidence:
              - episode: ep_2024-01-01_001
                start: 6
                end: 40
                kind: user
                hash: abc123def456
              source_episodes:
              - ep_2024-01-01_001

            """
        }
        return prose + "\n" + fence + "```\n"
    }()

    static let entity = Entity(id: ownerId, name: "Owner Example", type: .person, status: .active, confidence: 1,
                               created: "2026-10-07", lastReferenced: "2026-10-07", decayRate: 0, sourceEpisodes: [],
                               tags: ["owner"], related: [], version: 1, markdownContent: markdown, history: [])

    static let provenance: EntityProvenance = {
        let conversations = (0..<50).map { i in
            ProvenanceConversation(conversationId: "conv-\(i)", episodeId: "ep_2024-01-0\(1 + i % 9)_\(i)",
                                   episodeIds: (0..<6).map { "ep_2024-01-0\(1 + i % 9)_\(i)_\($0)" },
                                   title: "Conversation \(i)", origin: "chatgpt-export",
                                   timestamp: "2024-01-0\(1 + i % 9)T10:00:00Z", claimCount: 70 - i)
        }
        return EntityProvenance(entityId: ownerId, conversations: conversations,
                                totals: ProvenanceTotals(claims: claimCount, conversations: 1_519,
                                                         firstSaid: "2023-03-01", lastSaid: "2026-09-30T10:00:00Z"))
    }()

    static let nodes: [GraphNode] = [GraphNode(id: ownerId, name: "Owner Example", type: .person, degree: 1_315,
                                               isOwner: true)]
        + pages.enumerated().map { i, id in
            GraphNode(id: id, name: id, type: [.project, .concept, .tool, .person][i % 4], degree: 1 + i % 17)
        }

    static let edges: [GraphEdge] = (0..<1_315).map { GraphEdge(source: ownerId, target: pages[$0], label: "uses") }
        + (0..<3_700).map { GraphEdge(source: pages[$0 % pageCount], target: pages[($0 * 13 + 1) % pageCount],
                                      label: "relates to") }
}
