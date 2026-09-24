import Foundation

/// Round-4 D5 (C5) — `GET /agents/setup?harness=<id>`, decoded leniently (R-PP2's house rule): a backend one field
/// ahead or behind never fails the Agents page. `config.value` is deliberately NOT decoded — the app writes only the
/// Claude desktop entry it computed itself (R-FA15), so nothing off the wire can reach a file.
struct AgentSetupPrompt: Decodable, Equatable {
    struct Config: Decodable, Equatable {
        let path: String
        let key: String
    }

    var harness: String
    var kind: String
    var title: String
    var prompt: String?
    var argv: [[String]]
    var display: [String]
    var deeplink: String?
    var config: Config?
    var note: String?

    enum CodingKeys: String, CodingKey { case harness, kind, title, prompt, argv, display, deeplink, config, note }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        harness = c.lenient(.harness, "")
        kind = c.lenient(.kind, "")
        title = c.lenient(.title, "")
        prompt = c.lenient(.prompt)
        argv = c.lenient(.argv, [])
        display = c.lenient(.display, [])
        deeplink = c.lenient(.deeplink)
        config = c.lenient(.config)
        note = c.lenient(.note)
    }
}
