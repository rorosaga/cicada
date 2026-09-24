import SwiftUI

/// The G122 engine-and-model picker, as a row of cards with
/// real marks (R-E4): Auto, Claude plan, ChatGPT plan, Ollama, API key — the
/// five candidates `GET /sleep/engine` probes (`auto`, `agent`, `codex`,
/// `local`, `byok`), each deciding its own selectability and caption through
/// `EngineOption` (R-E25), a model field whose shape depends on which
/// candidate is selected, the Claude plan's extra-usage switch (R-E13), and both ruling-4 previews rendered side by side so a
/// prefs-chosen "agent" that silently degrades to `litellm` on the nightly
/// schedule is visible rather than a surprise. Never a price, never a token
/// count anywhere in this chooser (G124) — the wire models it reads
/// (`SleepEngineCandidate`/`SleepEnginePreview`) carry nothing of the kind.
///
/// Ruling 6: mutations go through `SleepEngineViewModel.set` as a plain
/// round trip — no optimistic apply, no rollback. The server's echoed
/// response (re-derived through the exact function a subsequent GET would
/// call) is simply assigned back, so this view never renders a locally
/// guessed state that could drift from what was actually persisted.
///
/// Extracted for G139 (R-O8) so Settings → Engines and onboarding render one
/// component: `EngineCard` is this chooser in a glass card.
struct EngineChooser: View {
    @Environment(SleepEngineViewModel.self) private var vm
    /// R-E24: the Plans & keys POWERS line follows this card's choice, and
    /// `/connections` is not a `/sync/version` component — so a mode change
    /// refreshes that one domain itself.
    @Environment(Store.self) private var store

    @State private var selectedMode: String = "auto"
    @State private var selectedModel: String = ""
    @State private var loadedOnce = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let response = vm.response {
                content(for: response)
            } else if let error = vm.errorMessage {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task {
            // Guarded like `SettingsSleepView`'s own `.task` — a chooser that
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
        .settingsRow(.engineChoice)

        if let hint = EngineOption.signInHint(response.candidates) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                SettingsInlineLink(section: .plansAndKeys, label: Copy.plansAndKeys)
                    .font(CicadaTheme.captionFont)
            }
        }

        if let candidate = response.candidates.first(where: { $0.id == selectedMode }) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                stateLine(for: candidate)
                modelField(for: candidate)
            }
            .settingsRow(.engineModel)
        }

        if EngineOption.showsOverageToggle(selectedMode: selectedMode) {
            overageToggle(response)
                .settingsRow(.engineOverage)
        }

        if let preview = response.preview {
            previewSection(preview)
                .settingsRow(.enginePreview)
        }
    }

    /// R-HS7 — the write rule is `EngineWrite`, shared with the Sleep page's quick menu, so a tap
    /// on either surface writes the same thing.
    private func select(_ candidate: SleepEngineCandidate) {
        guard let write = EngineWrite.choosing(candidate, current: selectedMode) else { return }
        selectedMode = write.mode
        selectedModel = write.model ?? ""
        commit(write)
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
                    .onSubmit { commit(EngineWrite(mode: candidate.id, model: selectedModel)) }
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
                let write = EngineWrite.model(newValue, mode: candidate.id, current: selectedModel)
                selectedModel = newValue
                if let write { commit(write) }
            }
        )
    }

    private func freeTextModelBinding(for candidate: SleepEngineCandidate) -> Binding<String> {
        Binding(get: { selectedModel }, set: { selectedModel = $0 })
    }

    @ViewBuilder
    private func previewSection(_ preview: SleepEnginePreviews) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            // R-HS11 — one pair of labels app-wide: this chooser, Settings → Sleep and the Sleep
            // page's quick menu said the same two facts two ways before DS-3b.
            Self.previewRow(preview.manual, label: Copy.EngineMenu.whenYouStart)
            Self.previewRow(preview.scheduled, label: Copy.EngineMenu.scheduledCycles)
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

    /// One "What runs" line wearing its engine's mark — the same vendor mark
    /// the chosen card wears (G139: a named service shows its real mark).
    /// Internal and static so the Sleep page's read-only engine row draws the
    /// same marked line (Task 2 review round 1) instead of a bare-text twin.
    static func previewRow(_ preview: SleepEnginePreview, label: String) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            LogoImage.platformTile(name: EngineOption.previewMark(engine: preview.engine) ?? "",
                                   size: CicadaTheme.scaled(16), systemFallback: "key.fill")
            Text(Self.previewLine(preview, label: label))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    private func commit(_ write: EngineWrite) {
        Task { @MainActor in
            await vm.apply(write)
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
/// `iconHover` once they land. Internal, not private: `EngineCard`'s
/// `.compact` form (the Welcome, R-IB13) draws the same card.
struct EngineOptionCard: View {
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
