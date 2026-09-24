import SwiftUI

/// The engine picker in a glass card, or — `.compact` — the Welcome's form of
/// it. `.full` is `EngineChooser`, the one component Settings → Engines renders
/// too (G139, R-O8).
///
/// Track I part b (R-IB13) adds `Style.compact`, the form onboarding shows
/// through `EngineChoice`: the four engines a new person can name, each with
/// its cost model in words (G117, never a price), a ring on the pick or else on
/// the engine that can run, and one honesty line — no model field, no overage
/// switch, no previews (Settings → Engines keeps those). With a `pick` binding
/// a click only moves the ring and the Welcome's Start writes it; without one a
/// click commits through `SleepEngineViewModel.set` as the chooser does.
struct EngineCard: View {
    enum Style { case full, compact }

    var style: Style = .full
    /// The Welcome's local pick (R-IB13): set, a click rings and writes nothing.
    var pick: Binding<String?>? = nil

    var body: some View {
        switch style {
        case .full:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                SettingsGroupHeader("Engine")
                EngineChooser()
            }
            .padding(CicadaTheme.spacingLG)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassCard()
        case .compact:
            CompactEngineChooser(pick: pick)
        }
    }
}

/// `.compact`'s body — its own view so the full chooser's state and the
/// Welcome's never share a `@State`.
private struct CompactEngineChooser: View {
    let pick: Binding<String?>?

    @Environment(SleepEngineViewModel.self) private var vm
    /// R-E24: the Plans & keys POWERS line follows this card's choice, and
    /// `/connections` is not a `/sync/version` component — so a mode change
    /// refreshes that one domain itself.
    @Environment(Store.self) private var store

    /// R-AG12 — the selected CARD (`response.selected`), so OpenRouter and the API key stay apart.
    @State private var selectedCard: String = "auto"
    @State private var selectedModel: String = ""
    @State private var loadedOnce = false

    var body: some View { compactBody }

    /// R-IB13 — sits inside a host card (the Welcome's checklist, Getting
    /// started), so no label, no glass and no padding of its own.
    private var compactBody: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let response = vm.response {
                compactContent(for: response)
            } else if let error = vm.errorMessage {
                Text(error)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task { await loadOnce() }
        .onChange(of: vm.response) { _, _ in syncFromResponse() }
    }

    /// Guarded like `EngineChooser`'s own `.task` — a card that
    /// re-appears (switching Settings sections and back) must not
    /// re-fetch and stomp an edit the user just made.
    private func loadOnce() async {
        guard !loadedOnce else { return }
        loadedOnce = true
        await vm.load()
        syncFromResponse()
    }

    @ViewBuilder
    private func compactContent(for response: SleepEngineResponse) -> some View {
        let connections = store.connections.value ?? []
        let hasKey = EngineReadiness.hasKey(connections)
        let readiness = EngineReadiness.resolve(candidates: response.candidates, connections: connections,
                                                preview: response.preview)
        let ringed = EngineOption.ringed(pick: pick?.wrappedValue, readiness: readiness)
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(128)), spacing: CicadaTheme.spacingSM)],
                  alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(EngineOption.compactCandidates(response.candidates)) { candidate in
                let selected = candidate.id == ringed
                EngineOptionCard(
                    candidate: candidate,
                    isSelected: selected,
                    isSelectable: EngineOption.isSelectable(candidate, selectedMode: selectedCard),
                    costModel: EngineOption.costModel(for: candidate.id),
                    caption: EngineOption.compactCaption(for: candidate, hasKey: hasKey),
                    showsWillRead: selected
                ) { select(candidate) }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Sleep engine")

        if let hint = EngineOption.signInHint(response.candidates) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                SettingsInlineLink(section: .plansAndKeys, label: Copy.plansAndKeys)
                    .font(CicadaTheme.captionFont)
            }
        }

        CompactEngineLine(response: response, readiness: readiness,
                          pickLabel: pick?.wrappedValue.flatMap { id in response.candidates.first { $0.id == id }?.label })
    }

    /// Mirrors `SettingsSleepView.syncScheduleState()` — local `@State`
    /// tracks the server's response so a `Picker`'s `selection` binding has
    /// somewhere to live, but the response itself (not this local copy) is
    /// what every read of `candidate.models`/`preview` ultimately reflects.
    private func syncFromResponse() {
        guard let response = vm.response else { return }
        selectedCard = response.selected
        selectedModel = response.model
    }

    private func select(_ candidate: SleepEngineCandidate) {
        // R-IB13: with a pick binding a click only rings the card — Start
        // writes it. The already-saved engine is still a pick the ring must
        // show, so the equality guard below does not apply here.
        if let pick {
            if EngineOption.isSelectable(candidate, selectedMode: selectedCard) { pick.wrappedValue = candidate.id }
            return
        }
        // R-AG12 / R-HS7: the one write rule, so a card becomes its mode in one place.
        guard let write = EngineWrite.choosing(candidate, current: selectedCard) else { return }
        selectedCard = candidate.id
        selectedModel = write.model ?? ""
        commit(write)
    }

    private func commit(_ write: EngineWrite) {
        Task { @MainActor in
            await vm.apply(write)
            // R-E24: POWERS follow the chosen engine — refresh that one domain
            // now (the same call `ConnectionsViewModel` makes after a change).
            await store.refresh([.connections])
        }
    }
}

/// The honesty line under `.compact`'s cards (R-IB13) plus who sees what is
/// read. Its own view so only `.compact` reads `SleepViewModel` (the schedule
/// `HonestyInputs` needs) — `.full` never touches it.
private struct CompactEngineLine: View {
    let response: SleepEngineResponse
    let readiness: EngineReadiness
    let pickLabel: String?
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    var body: some View {
        let inputs = HonestyInputs.from(schedule: sleepVM.schedule, response: response,
                                        connections: store.connections.value ?? [])
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(EngineChoiceLine.text(pickLabel: pickLabel, readiness: readiness, inputs: inputs))
            Text(Copy.welcomeProviderLine)
        }
        .font(CicadaTheme.captionFont)
        .foregroundStyle(CicadaTheme.textTertiary)
        .fixedSize(horizontal: false, vertical: true)
    }
}
