import SwiftUI

/// Settings → Sleep's G122 engine-and-model picker, as a row of cards with
/// real marks (R-E4): Auto, Claude plan, ChatGPT plan, Ollama, API key — the
/// five candidates `GET /sleep/engine` probes (`auto`, `agent`, `codex`,
/// `local`, `byok`), each deciding its own selectability and caption through
/// `EngineOption` (R-E25), a model field whose shape depends on which
/// candidate is selected, the Claude plan's extra-usage switch (R-E13), and both ruling-4 previews rendered side by side so a
/// prefs-chosen "agent" that silently degrades to `litellm` on the nightly
/// schedule is visible rather than a surprise. Never a price, never a token
/// count anywhere on this card (G124) — the wire models it reads
/// (`SleepEngineCandidate`/`SleepEnginePreview`) carry nothing of the kind.
///
/// Ruling 6: mutations go through `SleepEngineViewModel.set` as a plain
/// round trip — no optimistic apply, no rollback. The server's echoed
/// response (re-derived through the exact function a subsequent GET would
/// call) is simply assigned back, so this view never renders a locally
/// guessed state that could drift from what was actually persisted.
///
/// Track I part b (R-IB13) adds `Style.compact`, the form onboarding shows
/// through `EngineChoice`: the four engines a new person can name, each with
/// its cost model in words (G117, never a price), a ring on the pick or else on
/// the engine that can run, and one honesty line — no model field, no overage
/// switch, no previews (Settings keeps those). With a `pick` binding a click
/// only moves the ring and the Welcome's Start writes it; without one a click
/// commits exactly as `.full` does.
struct EngineCard: View {
    enum Style { case full, compact }

    var style: Style = .full
    /// The Welcome's local pick (R-IB13): set, a click rings and writes nothing.
    var pick: Binding<String?>? = nil

    @Environment(SleepEngineViewModel.self) private var vm
    /// R-E24: the Plans & keys POWERS line follows this card's choice, and
    /// `/connections` is not a `/sync/version` component — so a mode change
    /// refreshes that one domain itself.
    @Environment(Store.self) private var store

    @State private var selectedMode: String = "auto"
    @State private var selectedModel: String = ""
    @State private var loadedOnce = false

    /// Explicit because the private `@State`s would make the synthesized
    /// memberwise initializer private too; `EngineCard()` stays `.full`.
    init(style: Style = .full, pick: Binding<String?>? = nil) {
        self.style = style
        self.pick = pick
    }

    var body: some View {
        switch style {
        case .full: fullBody
        case .compact: compactBody
        }
    }

    private var fullBody: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("ENGINE")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            if let response = vm.response {
                content(for: response)
            } else if let error = vm.errorMessage {
                Text(error)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .task { await loadOnce() }
        .onChange(of: vm.response) { _, _ in syncFromResponse() }
    }

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

    /// Guarded like `SettingsSleepView`'s own `.task` — a card that
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
                    isSelectable: EngineOption.isSelectable(candidate, selectedMode: selectedMode),
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
                SettingsSectionLink(section: .plansAndKeys, label: Copy.plansAndKeys)
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
        selectedMode = response.mode
        selectedModel = response.model
    }

    @ViewBuilder
    private func content(for response: SleepEngineResponse) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(112)), spacing: CicadaTheme.spacingSM)],
                  alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(response.candidates) { candidate in
                EngineOptionCard(
                    candidate: candidate,
                    isSelected: candidate.id == selectedMode,
                    isSelectable: EngineOption.isSelectable(candidate, selectedMode: selectedMode)
                ) { select(candidate) }
            }
        }

        if let hint = EngineOption.signInHint(response.candidates) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                SettingsSectionLink(section: .plansAndKeys, label: Copy.plansAndKeys)
                    .font(CicadaTheme.captionFont)
            }
        }

        if let candidate = response.candidates.first(where: { $0.id == selectedMode }) {
            stateLine(for: candidate)
            modelField(for: candidate)
        }

        if EngineOption.showsOverageToggle(selectedMode: selectedMode) {
            overageToggle(response)
        }

        if let preview = response.preview {
            previewSection(preview)
        }
    }

    private func select(_ candidate: SleepEngineCandidate) {
        // R-IB13: with a pick binding a click only rings the card — Start
        // writes it. The already-saved engine is still a pick the ring must
        // show, so the equality guard below does not apply here.
        if let pick {
            if EngineOption.isSelectable(candidate, selectedMode: selectedMode) { pick.wrappedValue = candidate.id }
            return
        }
        guard candidate.id != selectedMode else { return }
        selectedMode = candidate.id
        let defaultModel = candidate.models.first ?? ""
        selectedModel = defaultModel
        commit(mode: candidate.id, model: defaultModel.isEmpty ? nil : defaultModel)
    }

    /// R-E13: off by default; only the switch sends `allowOverage`, so a mode
    /// or model change elsewhere on this card never flips it.
    @ViewBuilder
    private func overageToggle(_ response: SleepEngineResponse) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Toggle(Copy.keepGoingOnExtraUsage, isOn: Binding(
                get: { response.allowOverage },
                set: { on in
                    Task { @MainActor in
                        await vm.set(mode: selectedMode, model: nil, disambiguationModel: nil, allowOverage: on)
                    }
                }
            ))
            .toggleStyle(.switch)
            .font(CicadaTheme.captionFont)
            Text(Copy.keepGoingOnExtraUsageExplainer)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func stateLine(for candidate: SleepEngineCandidate) -> some View {
        if let detail = candidate.detail, !detail.isEmpty {
            Text(detail)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// The model field's shape depends entirely on which candidate is
    /// selected — a plan's model (the Claude aliases, or the ChatGPT plan's
    /// live `model/list`, default first), a local Ollama tag, or nothing at all for
    /// an API key (that model lives on the Plans & keys page, not here).
    @ViewBuilder
    private func modelField(for candidate: SleepEngineCandidate) -> some View {
        switch candidate.id {
        case "agent", "codex":
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if !candidate.models.isEmpty {
                    Picker("Model", selection: modelBinding(for: candidate)) {
                        ForEach(candidate.models, id: \.self) { model in
                            Text(model).tag(model)
                        }
                    }
                    .labelsHidden()
                }
                TextField("Model id", text: freeTextModelBinding(for: candidate))
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.captionFont)
                    .onSubmit { commit(mode: candidate.id, model: selectedModel) }
            }
        case "local":
            let guideState = OllamaGuideState.from(candidate: candidate)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if !candidate.models.isEmpty {
                    Picker("Model", selection: modelBinding(for: candidate)) {
                        ForEach(candidate.models, id: \.self) { model in
                            Text(model).tag(model)
                        }
                    }
                    .labelsHidden()
                }
                if let command = guideState.command {
                    CommandBox(command: command)
                }
            }
        case "byok":
            Text("Change it in \(Copy.settingsPlansAndKeys).")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        default:
            EmptyView()
        }
    }

    private func modelBinding(for candidate: SleepEngineCandidate) -> Binding<String> {
        Binding(
            get: { selectedModel },
            set: { newValue in
                selectedModel = newValue
                commit(mode: candidate.id, model: newValue)
            }
        )
    }

    private func freeTextModelBinding(for candidate: SleepEngineCandidate) -> Binding<String> {
        Binding(get: { selectedModel }, set: { selectedModel = $0 })
    }

    @ViewBuilder
    private func previewSection(_ preview: SleepEnginePreviews) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Self.previewLine(preview.manual, label: "Next cycle you start"))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            Text(Self.previewLine(preview.scheduled, label: "Nightly schedule"))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            // Ruling 4 stays binding and VISIBLE: a scheduled cycle never
            // spends plan quota. The caption only earns its place when the
            // two previews actually diverge — an `auto`/`byok` choice that
            // never touches the plan has nothing to disclose here.
            if preview.manual.engine != preview.scheduled.engine {
                Text(Copy.scheduledNeverSpendsPlans)
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.top, CicadaTheme.spacingXS)
    }

    private func commit(mode: String, model: String?) {
        Task { @MainActor in
            await vm.set(mode: mode, model: model, disambiguationModel: nil)
            // R-E24: POWERS follow the chosen engine — refresh that one domain
            // now (the same call `ConnectionsViewModel` makes after a change).
            await store.refresh([.connections])
        }
    }

    /// Pure formatter shared by both preview lines above —
    /// `"<label>: <engine word> · <model>"` — unit-tested directly
    /// (`EngineCardTests.testPreviewLineFormatting`) without standing up a
    /// view. The engine half is exactly `Copy.engineLabel`'s mapping
    /// (`claude-cli|codex-cli|ollama|litellm`), never a fresh coinage.
    static func previewLine(_ preview: SleepEnginePreview, label: String) -> String {
        "\(label): \(Copy.engineLabel(preview.engine)) · \(preview.model)"
    }
}

/// One card in the engine row. Hover uses the codebase's `.onHover`
/// highlight pattern (R-E27) — Track M2 swaps in Meadow's `hoverLift` /
/// `iconHover` once they land.
private struct EngineOptionCard: View {
    let candidate: SleepEngineCandidate
    let isSelected: Bool
    let isSelectable: Bool
    /// `.compact` only (R-IB13): how the option is paid for, in words (G117) —
    /// declared before `onSelect` so `.full`'s trailing-closure call is untouched.
    var costModel: String? = nil
    /// `.compact`'s state caption (the key card reads `Store.connections`, F6);
    /// nil keeps `.full`'s `EngineOption.caption(for:)` byte for byte.
    var caption: String? = nil
    var showsWillRead = false
    let onSelect: () -> Void
    @State private var isHovered = false

    private var markSize: CGFloat { CicadaTheme.scaled(28) }
    private var captionText: String { caption ?? EngineOption.caption(for: candidate) }
    private var accessibilityText: String {
        [candidate.label, costModel, captionText, showsWillRead ? Copy.welcomeWillRead : nil]
            .compactMap { $0 }.joined(separator: ", ")
    }

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                mark
                Text(candidate.label)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                if let costModel {
                    Text(costModel)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(captionText)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                if showsWillRead {
                    Text(Copy.welcomeWillRead)
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.accent)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingSM)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isHovered && isSelectable ? CicadaTheme.surfaceHover : CicadaTheme.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(isSelected ? CicadaTheme.accent : CicadaTheme.border, lineWidth: isSelected ? 2 : 1)
            )
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!isSelectable)
        .opacity(isSelectable ? 1 : 0.55)
        .onHover { isHovered = $0 }
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    @ViewBuilder
    private var mark: some View {
        if let logo = EngineOption.logoName(for: candidate.id) {
            LogoImage.platformTile(name: logo, size: markSize,
                                   systemFallback: EngineOption.symbol(for: candidate.id))
        } else {
            Image(systemName: EngineOption.symbol(for: candidate.id))
                .font(CicadaTheme.font(size: 14, weight: .medium))
                .foregroundStyle(CicadaTheme.accent)
                .frame(width: markSize, height: markSize)
                .background(RoundedRectangle(cornerRadius: markSize * 0.2).fill(CicadaTheme.surfaceElevated))
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
