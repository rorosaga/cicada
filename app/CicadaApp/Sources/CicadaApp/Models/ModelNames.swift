import Foundation

/// Round-4 C3/C4 (D1, R-FA14) — a model id as a person reads it and an effort level in words, for every surface
/// that names who wrote a belief. D1 lifted G49's reservation for harness writes: capture records the model and
/// effort of each agent turn, and a write is joined to its turn at read. Pure; `ModelNamesTests`.
enum ModelNames {
    /// Harnesses whose Stop hook reads the transcript (G105), so their turns can carry a model. Any other app that
    /// writes through MCP never tells Cicada its model — D1's "model not shared by this app".
    static let capturingHarnesses: Set<String> = ["claude-code", "codex"]

    private static let claudeFamilies = ["opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"]
    private static let words = ["codex": "Codex", "mini": "mini", "nano": "nano", "pro": "Pro", "max": "Max",
                                "turbo": "Turbo", "flash": "Flash", "lite": "Lite"]

    /// "claude-opus-5-5" → "Opus 5.5"; an id this does not recognise is shown exactly as sent — its own honest name.
    static func display(_ raw: String) -> String {
        var id = raw.trimmingCharacters(in: .whitespaces)
        if let bracket = id.firstIndex(of: "[") { id = String(id[..<bracket]) }   // "[1m]", a context-size tag
        var parts = id.lowercased().split(separator: "-").map(String.init)
        if let last = parts.last, last.count == 8, last.allSatisfy(\.isNumber) { parts.removeLast() }   // a date stamp
        guard let head = parts.first else { return raw }
        let rest = Array(parts.dropFirst())
        switch head {
        case "claude": return claude(rest) ?? raw
        case "gpt": return gpt(rest) ?? raw
        case "gemini": return gemini(rest) ?? raw
        default: return raw
        }
    }

    private static func isNumber(_ s: String) -> Bool { !s.isEmpty && s.allSatisfy(\.isNumber) }

    private static func claude(_ p: [String]) -> String? {
        if let first = p.first, let family = claudeFamilies[first] {            // claude-opus-5-5
            let version = Array(p.dropFirst())
            guard !version.isEmpty, version.allSatisfy(isNumber) else { return nil }
            return "\(family) \(version.joined(separator: "."))"
        }
        if let last = p.last, let family = claudeFamilies[last], p.count > 1,  // claude-3-5-sonnet
           p.dropLast().allSatisfy(isNumber) {
            return "\(family) \(p.dropLast().joined(separator: "."))"
        }
        return nil
    }

    private static func gpt(_ p: [String]) -> String? { versioned("GPT-", p) }          // gpt-5.5-codex, gpt-4o-mini
    private static func gemini(_ p: [String]) -> String? { versioned("Gemini ", p) }    // gemini-2.5-pro

    /// A version that starts with a digit, then only words this table knows; anything else is not ours to rename.
    private static func versioned(_ prefix: String, _ p: [String]) -> String? {
        guard let version = p.first, version.first?.isNumber == true else { return nil }
        var out = prefix + version
        for w in p.dropFirst() {
            guard let word = words[w] else { return nil }
            out += " \(word)"
        }
        return out
    }

    /// C1's effort enum in words; anything else says nothing rather than a guess.
    static func effort(_ raw: String?) -> String? {
        switch raw?.lowercased() {
        case "minimal": "minimal effort"
        case "low": "low effort"
        case "medium": "medium effort"
        case "high": "high effort"
        case "xhigh": "extra-high effort"
        case "max": "max effort"
        default: nil
        }
    }

    /// "Opus 5.5 · high effort", "Opus 5.5", or nil with no model.
    static func line(model: String?, effort: String?) -> String? {
        guard let model, !model.isEmpty else { return nil }
        return [display(model), self.effort(effort)].compactMap { $0 }.joined(separator: " · ")
    }

    /// "Claude Code · Opus 5.5 · high effort". With no model: an app that never tells adds "model not shared by this
    /// app"; a capturing harness (a write from before D1) adds nothing — never a guess.
    static func agentLine(agent: String?, harness: String?, model: String?, effort: String?) -> String? {
        let modelLine = line(model: model, effort: effort)
        var parts = [agent, modelLine].compactMap { $0 }.filter { !$0.isEmpty }
        if modelLine == nil, let harness, !harness.isEmpty, !["unknown", "mcp"].contains(harness),
           !capturingHarnesses.contains(harness), agent != nil {
            parts.append(Copy.Provenance.modelNotShared)
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
