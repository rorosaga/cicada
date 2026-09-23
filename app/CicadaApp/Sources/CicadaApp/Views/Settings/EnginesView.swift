import SwiftUI

/// Settings → Engines (G139, A3): the one page that answers "who does
/// Cicada's thinking". The card row, model and What-runs block are
/// `EngineChooser` (Track E's, unchanged, R-O8). "Use my Claude plan when I
/// start a cycle" is the toggle that used to sit on the Claude plan's card —
/// same pref, same endpoint, and ruling 4 still holds (the explainer says so).
///
/// G139 final review — the switch is shown only under the API key card, and
/// says what it does there. `engine_select.resolve_llm_mode` reads
/// `use_for_sleep` only when the configured mode is `byok`; Auto tries the
/// Claude plan first either way. A3's "Auto may use my Claude plan" was a
/// switch that did nothing under Auto and quietly moved API-key cycles onto
/// the plan — the opposite of what its words said.
///
/// The plan-window percentage stays hidden (spec decision 17): nothing on
/// this page reads it.
struct EnginesView: View {
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    /// The chooser's view model. A flip of the switch changes what
    /// `preview.manual` resolves to, and ruling 6 gives `/sleep/engine` no
    /// Store domain to push that — so the setter reloads it, and the
    /// chooser's `onChange(of: vm.response)` and the Sleep page's engine line
    /// follow (G139 final review; the switch and the preview used to sit on
    /// different pages, where navigating between them hid the staleness).
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store

    private var claudePlan: ConnectionStatus? {
        (store.connections.value ?? []).first { $0.id == "claude-plan" }
    }

    /// `byok` is also what the server answers with no stored choice, so a
    /// fresh install that has signed into the plan sees the switch too.
    private var apiKeyChosen: Bool { engineVM.response?.mode == "byok" }

    var body: some View {
        SettingsPage(section: .engines) {
            SettingsGroupCard(header: Copy.enginesChooseGroup) {
                EngineChooser().padding(CicadaTheme.spacingMD)
            }
            if apiKeyChosen, let plan = claudePlan, plan.showsSleepEngineToggle {
                SettingsGroupCard(header: Copy.apiKeyGroup) {
                    SettingsRow(.engineAutoClaude, title: Copy.useClaudePlanWhenIStart, detail: Copy.sleepEngineExplainer) {
                        Toggle(Copy.useClaudePlanWhenIStart, isOn: Binding(
                            get: { plan.useForSleep },
                            set: { on in
                                Task {
                                    await connectionsVM.setUseForSleep(plan.id, on: on)
                                    await engineVM.load()
                                }
                            }
                        ))
                        .toggleStyle(.switch)
                        .labelsHidden()
                    }
                    // A failed flip is toasted in the main window, which may be
                    // closed; say it here, where the switch is.
                    if let error = connectionsVM.errorMessage {
                        Text(error)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.spacingMD)
                            .padding(.bottom, CicadaTheme.spacingSM)
                    }
                }
            }
            SettingsGroupCard(header: Copy.askGroup) {
                SettingsRow(.engineAsk, title: Copy.askTitle, detail: Copy.askFollowsEngine)
            }
        }
    }
}
