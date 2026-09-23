import XCTest
@testable import CicadaApp

/// G136 design §3.10 / plan R-SU24 — the local tier's budget at the live
/// bank's scale, from a fixed seed and made-up syllables (the backend
/// latency test's rule, G136 R18: the same bank on every machine, no names).
/// The design's 8 ms is a RELEASE number; a debug `swift test` gates at
/// 300 ms, which still fails an accidental O(n²) (plan R-SU24). The orchestrator runs:
/// `swift test -c release -Xswiftc -enable-testing --filter QuickIndexLatencyTests`.
final class QuickIndexLatencyTests: XCTestCase {
    #if DEBUG
    static let budgetMs = 300.0
    #else
    static let budgetMs = SearchTiming.localBudgetMs
    #endif

    func testALocalKeystrokeIsWithinBudgetAtTheLiveBanksScale() {
        var rng = FindSeededGenerator(seed: 7)
        let syllables = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
                         "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]
        func word() -> String {
            (0..<Int.random(in: 2...4, using: &rng)).map { _ in syllables.randomElement(using: &rng)! }.joined()
        }
        func sentence(_ n: Int) -> String { (0..<n).map { _ in word() }.joined(separator: " ") }
        var inputs = QuickIndexInputs()
        inputs.nodes = (0..<3000).map { i in
            FindFixtures.node("e-\(i)", "\(word()) \(word()) \(i)", tags: [word()], summary: sentence(28), degree: i % 17)
        }
        inputs.media = (0..<1500).map { i in
            FindFixtures.media("m-\(i)", title: sentence(6), url: "https://example.com/\(word())/\(i)",
                               site: "example.com", description: sentence(30))
        }
        inputs.inbox = (0..<200).map { i in
            FindFixtures.inbox("inbox-\(i)", question: "Still tracking \(word())?", entityName: word(), excerpt: sentence(40))
        }
        let buildStart = DispatchTime.now().uptimeNanoseconds
        let index = QuickIndex.build(inputs)
        let buildMs = Double(DispatchTime.now().uptimeNanoseconds - buildStart) / 1_000_000
        var queries = (0..<40).map { _ in String(word().prefix(Int.random(in: 1...6, using: &rng))) }
        queries += (0..<10).map { _ in "\(word()) \(word().prefix(3))" }
        for query in queries.prefix(5) { _ = index.query(query) }   // warm
        var samples: [Double] = []
        for query in queries {
            let start = DispatchTime.now().uptimeNanoseconds
            _ = FindMerge.fresh(query: query, local: index.query(query))
            samples.append(Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
        }
        samples.sort()
        let p50 = samples[samples.count / 2]
        let p95 = samples[Int(Double(samples.count - 1) * 0.95)]
        print("G136 local tier: 3,000 entities + 1,500 media + 200 inbox; build \(String(format: "%.0f", buildMs)) ms; "
              + "keystroke p50 \(String(format: "%.2f", p50)) ms, p95 \(String(format: "%.2f", p95)) ms (budget \(Self.budgetMs) ms)")
        XCTAssertLessThanOrEqual(p95, Self.budgetMs)
    }
}

/// SplitMix64 — a fixed-seed generator so the synthetic bank is identical on every machine.
struct FindSeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}
