import SwiftUI

/// Onboarding v2, step 2 (ruling 36 D1, G217, G50): who reads the memory. With a plan signed in, Auto already uses it —
/// said once with what runs ("Using your Claude plan" · "Cicada runs your own Claude Code."), and *Use an API key
/// instead* opens the same paste → Verify rows Settings → Intelligence draws (`IntelligenceRow`). With nothing that can
/// read, the plans and the keys show side by side, equal options. A local model is never offered here (D1). The step
/// writes only on a click inside a row (Sign in, Verify, Use) — Continue and Skip change nothing, so an untouched
/// step keeps the configured engine (R-OB5's rule, kept). DR-5 (no accent but the frame's one primary), DR-11, DR-37,
/// DR-40, DR-52 (each provider in its own mark, `LogoTile`).
struct IntelligenceStep: View {
    @Environment(Store.self) private var store
    @Environment(SleepEngineViewModel.self) private var engineVM
    @State private var directory = ProviderDirectory.shared
    @State private var showsKeys = false

    private var state: IntelligenceStepState { IntelligenceStepState.of(engineVM.response) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.intelTitle, subline: Copy.intelSubline)
            switch state {
            case let .plan(line, runs, mark):
                headline(mark: mark, title: line, detail: runs)
                keysToggle(Copy.intelUseKey)
                if showsKeys { group(Copy.Intelligence.keys, kind: "key") }
            case let .chosen(title, line, mark):
                headline(mark: mark, title: title, detail: line)
                keysToggle(Copy.intelUsePlan)
                if showsKeys { group(Copy.Intelligence.plans, kind: "plan") }
            case .nothing:
                Text(Copy.intelNothing)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                group(Copy.Intelligence.plans, kind: "plan")
                group(Copy.Intelligence.keys, kind: "key")
            }
        }
        .task {
            await directory.load()
            await engineVM.load()
        }
        // A sign-in or a verified key lands in /connections; the engine's answer follows it.
        .onChange(of: store.connections.value?.map(\.connected)) { _, _ in Task { await engineVM.load() } }
    }

    private func headline(mark: String, title: String, detail: String) -> some View {
        // The line already says it is in use ("Using your … plan"): no second status word (DR-38).
        ConnectionLine(logo: mark, name: title, systemFallback: "sparkles", detail: detail) { EmptyView() }
            .settingsCardSurface()
    }

    private func keysToggle(_ title: String) -> some View {
        TextButton(title: title, inline: true, flushLeading: true) { showsKeys.toggle() }
    }

    /// Settings → Intelligence's own rows for one kind — never the local row (D1: local is never pitched).
    @ViewBuilder
    private func group(_ header: String, kind: String) -> some View {
        let items = directory.intelligence.filter { pair in
            kind == "plan" ? pair.item.kind == "plan"
                : pair.item.kind == "key" && IntelligenceStepState.featuredKeys.contains(pair.item.connection)
        }
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(header).padding(.horizontal, CicadaTheme.spacingXS)
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.item.id) { index, pair in
                        if index > 0 { SettingsDivider() }
                        let id = ProviderDirectory.connectionId(pair.item.connection)
                        IntelligenceRow(umbrella: pair.umbrella, item: pair.item,
                                        connection: (store.connections.value ?? []).first { $0.id == id },
                                        inUse: inUse == id,
                                        canChoose: engineVM.response?.isPinnedByEnvironment == false,
                                        onUse: { use(pair.item) })
                    }
                }
                .settingsCardSurface()
                if kind == "key" {
                    OnboardingPointerLine(lead: Copy.intelMoreKeys, section: .intelligence,
                                          label: Copy.intelMoreKeysWhere)
                        .padding(.horizontal, CicadaTheme.spacingXS)
                }
            }
        }
    }

    private var inUse: String? {
        guard let response = engineVM.response, response.selected != "auto" else { return nil }
        return IntelligenceView.connection(forCard: response.selected, provider: response.provider)
    }

    private func use(_ item: ProviderIntelligence) {
        guard let response = engineVM.response,
              let write = IntelligenceView.write(using: item, response: response) else { return }
        Task { await engineVM.apply(write) }
    }
}
