import Foundation

/// Decision 5 / R-AG14 — "this is where information leaves your Mac", shown only for an engine that sends what
/// it reads to someone else, naming who. Ollama has no note (and the words never mention it), and Auto has none
/// when it would run on Ollama. Pure, so Settings → Engines and phase B's Who reads say the same thing.
enum LeavesMacNote {
    static func text(selected: String, provider: String?, manualEngine: String?,
                     providers: [SleepEngineProvider]) -> String? {
        guard let body = body(selected: selected, provider: provider, manualEngine: manualEngine,
                              providers: providers) else { return nil }
        return "\(Copy.leavesMacLead) \(body) \(Copy.leavesMacTail)"
    }

    private static func body(selected: String, provider: String?, manualEngine: String?,
                             providers: [SleepEngineProvider]) -> String? {
        switch selected {
        case "local": return nil
        case "agent": return Copy.leavesMacClaudePlan
        case "codex": return Copy.leavesMacChatGPTPlan
        case "openrouter": return Copy.leavesMacOpenRouter
        case "byok":
            if provider == "openrouter" { return Copy.leavesMacOpenRouter }
            // An env-pinned model whose provider is not in the picker still gets an honest sentence.
            guard let brand = providers.first(where: { $0.id == provider })?.label else { return Copy.leavesMacKeyUnknown }
            return Copy.leavesMacKey(brand)
        case "auto":
            // Auto names what a cycle you start would run (`preview.manual`), since that is what reads.
            switch manualEngine {
            case "ollama", nil: return nil
            case "claude-cli": return Copy.leavesMacClaudePlan
            case "codex-cli": return Copy.leavesMacChatGPTPlan
            default: return body(selected: "byok", provider: provider, manualEngine: nil, providers: providers)
            }
        default: return nil
        }
    }
}
