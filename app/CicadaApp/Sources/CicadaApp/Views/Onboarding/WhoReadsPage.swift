import SwiftUI

/// F-05 (G145; owner decision 5) — `EngineChooser` unchanged: OpenRouter's sign-in, the key-provider picker, Ollama
/// *Local*, `LeavesMacNote` only where reads leave the Mac, and both ruling-4 previews from the server (never a literal
/// line). A click writes through the chooser's one rule (R-AG12); this page writes nothing itself, so an untouched
/// choice keeps the configured engine (R-OB5, pinned by `OnboardingSourceTests`). DR-5, DR-40, DR-44.
struct WhoReadsPage: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.welcomeWhoReads, subline: Copy.whoReadsSubline)
            EngineChooser()
            Text(Copy.whoReadsNothingYet)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// The frame's foot line for this page (R-OB17, `WhoReadsFoot`): before the engine answers, the cautious
    /// "Everything else…" — never a promise that nothing leaves.
    @MainActor
    static func footLine(_ response: SleepEngineResponse?) -> String {
        guard let response else { return Copy.privacyEverythingElse }
        return WhoReadsFoot.line(note: LeavesMacNote.text(selected: response.selected, provider: response.provider,
                                                          manualEngine: response.preview?.manual.engine,
                                                          providers: response.providers))
    }
}
