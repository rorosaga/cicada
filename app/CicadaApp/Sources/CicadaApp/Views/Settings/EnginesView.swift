import SwiftUI

/// Settings → Engines (G139, A3): the one page that answers "who does
/// Cicada's thinking". The card row, model and What-runs block are
/// `EngineChooser` (Track E's, unchanged, R-O8). "Auto may use my Claude
/// plan" is the toggle that used to sit on the Claude plan's card — same
/// pref, same endpoint, and ruling 4 still holds (the explainer says so).
///
/// The plan-window percentage stays hidden (spec decision 17): nothing on
/// this page reads it.
struct EnginesView: View {
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    @Environment(Store.self) private var store

    private var claudePlan: ConnectionStatus? {
        (store.connections.value ?? []).first { $0.id == "claude-plan" }
    }

    var body: some View {
        SettingsPage(section: .engines) {
            SettingsGroupCard(header: Copy.enginesChooseGroup) {
                EngineChooser().padding(CicadaTheme.spacingMD)
            }
            if let plan = claudePlan, plan.showsSleepEngineToggle {
                SettingsGroupCard(header: Copy.autoGroup) {
                    SettingsRow(.engineAutoClaude, title: Copy.autoMayUseClaudePlan, detail: Copy.sleepEngineExplainer) {
                        Toggle(Copy.autoMayUseClaudePlan, isOn: Binding(
                            get: { plan.useForSleep },
                            set: { on in Task { await connectionsVM.setUseForSleep(plan.id, on: on) } }
                        ))
                        .toggleStyle(.switch)
                        .labelsHidden()
                    }
                }
            }
            SettingsGroupCard(header: Copy.askGroup) {
                SettingsRow(.engineAsk, title: Copy.askTitle, detail: Copy.askFollowsEngine)
            }
        }
    }
}
