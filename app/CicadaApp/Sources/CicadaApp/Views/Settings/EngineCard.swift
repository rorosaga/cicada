import SwiftUI

/// Settings → Sleep's G122 engine-and-model picker: a segmented control over
/// the five candidates `GET /sleep/engine` probes (`auto`, `agent`, `codex`,
/// `local`, `byok`), a model field whose shape depends on which candidate is
/// selected, and both ruling-4 previews rendered side by side so a
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
struct EngineCard: View {
    @Environment(SleepEngineViewModel.self) private var vm

    @State private var selectedMode: String = "auto"
    @State private var selectedModel: String = ""
    @State private var loadedOnce = false

    var body: some View {
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
        .task {
            // Guarded like `SettingsSleepView`'s own `.task` — a card that
            // re-appears (switching Settings sections and back) must not
            // re-fetch and stomp an edit the user just made.
            guard !loadedOnce else { return }
            loadedOnce = true
            await vm.load()
            syncFromResponse()
        }
        .onChange(of: vm.response) { _, _ in syncFromResponse() }
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
        Picker("Engine", selection: Binding(
            get: { selectedMode },
            set: { newValue in
                selectedMode = newValue
                let candidate = response.candidates.first { $0.id == newValue }
                let defaultModel = candidate?.models.first ?? ""
                selectedModel = defaultModel
                commit(mode: newValue, model: defaultModel.isEmpty ? nil : defaultModel)
            }
        )) {
            ForEach(response.candidates) { candidate in
                // R5: codex is a permanently-disabled row — shown so the
                // picker can explain why (its own `detail`), never
                // selectable, rather than silently omitting a row the
                // Plans & keys page's ChatGPT card might lead someone to
                // expect here.
                Text(candidate.label)
                    .tag(candidate.id)
                    .disabled(candidate.id == "codex")
            }
        }
        .pickerStyle(.segmented)
        .labelsHidden()

        if let candidate = response.candidates.first(where: { $0.id == selectedMode }) {
            stateLine(for: candidate)
            modelField(for: candidate)
        }

        if let preview = response.preview {
            previewSection(preview)
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
    /// selected — an Agent alias, a local Ollama tag, or nothing at all for
    /// an API key (that model lives on the Plans & keys page, not here).
    @ViewBuilder
    private func modelField(for candidate: SleepEngineCandidate) -> some View {
        switch candidate.id {
        case "agent":
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
                Text("Scheduled cycles never spend plan quota unless CICADA_LLM_MODE is set in api/.env.")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.top, CicadaTheme.spacingXS)
    }

    private func commit(mode: String, model: String?) {
        Task { @MainActor in
            await vm.set(mode: mode, model: model, disambiguationModel: nil)
        }
    }

    /// Pure formatter shared by both preview lines above —
    /// `"<label>: <engine word> · <model>"` — unit-tested directly
    /// (`EngineCardTests.testPreviewLineFormatting`) without standing up a
    /// view. The engine half is exactly `Copy.engineLabel`'s existing
    /// three-way mapping, never a fresh coinage.
    static func previewLine(_ preview: SleepEnginePreview, label: String) -> String {
        "\(label): \(Copy.engineLabel(preview.engine)) · \(preview.model)"
    }
}
