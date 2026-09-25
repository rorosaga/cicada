import SwiftUI

/// The G122 engine-and-model picker, as a row of cards with
/// real marks (R-E4): Auto, Claude plan, ChatGPT plan, OpenRouter, Ollama, API key — the
/// six candidates `GET /sleep/engine` probes (`auto`, `agent`, `codex`, `openrouter`,
/// `local`, `byok`; OpenRouter is `byok` under the hood, R-AG12), each deciding its own selectability and caption through
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
    /// R-AG10 / R-AG11 — Sign in with OpenRouter and a provider's key are saved through the same
    /// view model Plans & keys uses, so the key lands in `secrets.env` by one path.
    @Environment(ConnectionsViewModel.self) private var connections
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// R-AG12 — the selected CARD, not the mode: OpenRouter and the API key are both `byok`.
    @State private var selectedCard: String = "auto"
    @State private var selectedModel: String = ""
    @State private var loadedOnce = false
    /// Set when the person starts an OpenRouter sign-in (or pastes its key) HERE, so the card is
    /// chosen once the key lands — and only then; a sign-in finished on Plans & keys chooses nothing.
    @State private var startedSignIn = false
    @State private var showsOpenRouterPaste = false
    @State private var openRouterKeyDraft = ""
    @State private var providerKeyDraft = ""

    private static let openRouterConnection = "byok-openrouter"

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
        .onChange(of: openRouterConnected) { _, connected in
            guard connected else { return }
            Task { @MainActor in await openRouterDidConnect() }
        }
    }

    private var openRouterConnected: Bool {
        (store.connections.value ?? []).first { $0.id == Self.openRouterConnection }?.connected ?? false
    }

    /// The card from before the reload is still `connected: false`, so `isSelectable` would refuse
    /// it — reload first, then choose the RELOADED card.
    private func openRouterDidConnect() async {
        await vm.load()
        guard startedSignIn else { return }
        startedSignIn = false
        openRouterKeyDraft = ""
        showsOpenRouterPaste = false
        guard let card = vm.response?.candidates.first(where: { $0.id == "openrouter" }),
              let write = EngineWrite.choosing(card, current: selectedCard) else { return }
        selectedCard = card.id
        selectedModel = write.model ?? ""
        commit(write)
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

    @ViewBuilder
    private func content(for response: SleepEngineResponse) -> some View {
        EngineCardGrid(minimum: CicadaTheme.scaled(112), spacing: CicadaTheme.spacingSM) {
            ForEach(response.candidates) { candidate in
                EngineOptionCard(
                    candidate: candidate,
                    isSelected: candidate.id == selectedCard,
                    isSelectable: EngineOption.isSelectable(candidate, selectedMode: selectedCard),
                    // R-AG14 — how OpenRouter and Ollama are paid for is not obvious from their names.
                    costModel: ["openrouter", "local"].contains(candidate.id)
                        ? EngineOption.costModel(for: candidate.id) : nil,
                    tag: EngineOption.isLocal(candidate.id) ? Copy.engineLocalTag : nil
                ) { select(candidate) }
            }
        }
        .settingsRow(.engineChoice)

        if let openRouter = response.candidates.first(where: { $0.id == "openrouter" }), !openRouter.connected {
            openRouterSignIn
        }

        leavesMacNote(for: response)

        if let hint = EngineOption.signInHint(response.candidates) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(hint).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                SettingsInlineLink(section: .plansAndKeys, label: Copy.plansAndKeys)
                    .font(CicadaTheme.captionFont)
            }
        }

        if let candidate = response.candidates.first(where: { $0.id == selectedCard }) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                stateLine(for: candidate)
                modelField(for: candidate)
            }
            .settingsRow(.engineModel)
        }

        if EngineOption.showsOverageToggle(selectedMode: selectedCard) {
            overageToggle(response)
                .settingsRow(.engineOverage)
        }

        if let preview = response.preview {
            previewSection(preview)
                .settingsRow(.enginePreview)
        }
    }

    /// R-AG10 (DR-40) — under the grid while OpenRouter is not connected: signing in is one click,
    /// pasting a key the second way to fill the same connection.
    @ViewBuilder
    private var openRouterSignIn: some View {
        let waiting = connections.awaitingBrowser == Self.openRouterConnection
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.signInWithOpenRouter,
                              leading: AnyView(LogoImage(name: EngineOption.logoName(for: "openrouter") ?? "openrouter",
                                                         size: CicadaTheme.scaled(14))),
                              isDisabled: waiting) {
                    startedSignIn = true
                    Task { @MainActor in _ = await connections.beginLogin(Self.openRouterConnection) }
                }
                TextButton(title: Copy.pasteAKeyInstead) { showsOpenRouterPaste.toggle() }
            }
            if waiting {
                Text(Copy.openRouterFinishInBrowser)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if showsOpenRouterPaste {
                keyField(placeholder: Copy.pasteProviderKey(Copy.openRouterName), draft: $openRouterKeyDraft) { key in
                    startedSignIn = true
                    await connections.saveKey(Self.openRouterConnection, key: key)
                }
            }
        }
    }

    /// One paste-a-key row: a secure field and Save. The key goes to `saveKey` and is never kept
    /// past the save (secrets live only in `secrets.env`).
    private func keyField(placeholder: String, draft: Binding<String>,
                          save: @escaping (String) async -> Void) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            SecureField(placeholder, text: draft)
                .textFieldStyle(.roundedBorder)
                .font(CicadaTheme.captionFont)
                .frame(maxWidth: CicadaTheme.scaled(320))
            NeutralButton(title: Copy.keySave, size: .compact,
                          isDisabled: draft.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty) {
                let key = draft.wrappedValue.trimmingCharacters(in: .whitespaces)
                draft.wrappedValue = ""
                Task { @MainActor in await save(key) }
            }
        }
    }

    /// R-AG14 — where reads leave the Mac, only for an engine that sends them out; it fades
    /// (`CicadaMotion.hover`, instant under Reduce Motion) as the choice moves.
    @ViewBuilder
    private func leavesMacNote(for response: SleepEngineResponse) -> some View {
        let note = LeavesMacNote.text(selected: selectedCard, provider: response.provider,
                                      manualEngine: response.preview?.manual.engine, providers: response.providers)
        VStack(alignment: .leading, spacing: 0) {
            if let note {
                LeavesMacNoteRow(note: note).transition(.opacity)
            }
        }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: note)
    }

    /// R-HS7 — the write rule is `EngineWrite`, shared with the Sleep page's quick menu, so a tap
    /// on either surface writes the same thing.
    private func select(_ candidate: SleepEngineCandidate) {
        guard let write = EngineWrite.choosing(candidate, current: selectedCard) else { return }
        selectedCard = candidate.id
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
                        // The switch shows only for `agent`/`auto`, where card and mode agree; the
                        // response's mode is still the one that is written (R-AG12).
                        await vm.set(mode: vm.response?.mode ?? selectedCard, model: nil,
                                      disambiguationModel: nil, allowOverage: on)
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
    /// live `model/list`, default first), a local Ollama tag, OpenRouter's model id
    /// (a text field with a tested default; no catalog fetch), or the API key's provider
    /// picker (R-AG11), which writes that provider's default model.
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
                    .onSubmit { commit(EngineWrite(mode: EngineWrite.mode(of: candidate), model: selectedModel)) }
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
        case "openrouter":
            // R-AG12 — a model edit writes `byok`, never `mode: candidate.id` (a 422); the server
            // pins the judge to the same model (R-AG13).
            TextField(Copy.openRouterModel, text: freeTextModelBinding(for: candidate))
                .textFieldStyle(.roundedBorder)
                .font(CicadaTheme.captionFont)
                .onSubmit {
                    let id = EngineOption.openRouterModelID(selectedModel)
                    if let write = EngineWrite.model(id, mode: "byok", current: vm.response?.model ?? "") {
                        commit(write)
                    }
                }
        case "byok":
            if let response = vm.response { providerPicker(response) }
        default:
            EmptyView()
        }
    }

    /// R-AG11 — the API-key card's provider picker (Anthropic, OpenAI, Gemini, xAI, Groq,
    /// Mistral), each row wearing its mark; a pick writes that provider's default model. A provider
    /// without a key offers the paste field and where to get one, in place.
    @ViewBuilder
    private func providerPicker(_ response: SleepEngineResponse) -> some View {
        if !response.providers.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Picker(Copy.keyProvider, selection: providerBinding(response)) {
                    if response.provider.map({ id in !response.providers.contains { $0.id == id } }) ?? true {
                        Text("").tag("")
                    }
                    ForEach(response.providers) { provider in
                        Label {
                            Text(provider.label)
                        } icon: {
                            providerMark(provider)
                        }
                        .tag(provider.id)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: CicadaTheme.scaled(240), alignment: .leading)
                if let chosen = response.providers.first(where: { $0.id == response.provider }), !chosen.hasKey {
                    keyField(placeholder: Copy.pasteProviderKey(chosen.label), draft: $providerKeyDraft) { key in
                        await connections.saveKey(chosen.connectionId, key: key)
                        await vm.load()
                    }
                    if let url = URL(string: chosen.keyUrl), url.scheme == "https" {
                        TextButton(title: Copy.whereDoIGetOne) { NSWorkspace.shared.open(url) }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func providerMark(_ provider: SleepEngineProvider) -> some View {
        if let logo = ConnectionMark.logoName(connectionId: provider.connectionId) {
            LogoImage(name: logo, size: CicadaTheme.scaled(14))
        } else {
            Image(systemName: "key.fill")
        }
    }

    private func providerBinding(_ response: SleepEngineResponse) -> Binding<String> {
        Binding(
            get: { response.provider ?? "" },
            set: { id in
                guard let provider = response.providers.first(where: { $0.id == id }),
                      let write = EngineOption.providerWrite(provider, selectedCard: selectedCard,
                                                             currentModel: response.model) else { return }
                selectedCard = "byok"
                selectedModel = write.model ?? ""
                providerKeyDraft = ""
                commit(write)
            }
        )
    }

    private func modelBinding(for candidate: SleepEngineCandidate) -> Binding<String> {
        Binding(
            get: { selectedModel },
            set: { newValue in
                let write = EngineWrite.model(newValue, mode: EngineWrite.mode(of: candidate), current: selectedModel)
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
            LogoImage.platformTile(name: EngineOption.previewMark(engine: preview.engine, model: preview.model) ?? "",
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
    /// (`claude-cli|codex-cli|ollama|litellm`), never a fresh coinage — except a key run
    /// through OpenRouter, which names OpenRouter (`EngineOption.previewName`, R-AG12).
    static func previewLine(_ preview: SleepEnginePreview, label: String) -> String {
        "\(label): \(EngineOption.previewName(engine: preview.engine, model: preview.model)) · \(preview.model)"
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
    /// R-AG14 / DR-44 — one `Tag` beside the label (Ollama's "Local"); declared before `onSelect`
    /// so every trailing-closure call is untouched.
    var tag: String? = nil
    /// `.compact`'s state caption (the key card reads `Store.connections`, F6);
    /// nil keeps `.full`'s `EngineOption.caption(for:)` byte for byte.
    var caption: String? = nil
    var showsWillRead = false
    let onSelect: () -> Void
    @State private var isHovered = false

    private var markSize: CGFloat { CicadaTheme.scaled(28) }
    private var captionText: String { caption ?? EngineOption.caption(for: candidate) }
    private var accessibilityText: String {
        [candidate.label, tag, costModel, captionText, showsWillRead ? Copy.welcomeWillRead : nil]
            .compactMap { $0 }.joined(separator: ", ")
    }

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                mark
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(candidate.label)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let tag { Tag(text: tag) }
                }
                if let costModel {
                    Text(costModel)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(captionText)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                if showsWillRead {
                    Text(Copy.welcomeWillRead)
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.accent)
                }
            }
            // G122 live pass — fills the height its row offers (`EngineCardGrid`), so a card with a cost line
            // and a caption stands no taller than its neighbours; its words keep to the top.
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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

/// G122 live pass — the engine cards in rows of equal height. `LazyVGrid` sized each card to its own words, so the
/// OpenRouter card (its cost line wrapping over "Signed in") stood taller than Auto and the plans beside it and the
/// row's tops and bottoms stopped lining up. Columns follow `GridItem(.adaptive(minimum:))`'s rule; each row is as
/// tall as its tallest card, and every card in it is offered that height (`EngineOptionCard` fills it). Settings →
/// Engines, onboarding's Who reads (the same `EngineChooser`) and `.compact` all lay their cards out here.
struct EngineCardGrid: Layout {
    var minimum: CGFloat
    var spacing: CGFloat

    /// `GridItem.adaptive`'s count: as many `minimum`-wide columns as fit, never fewer than one. An unbounded width
    /// (an ideal-size pass) gets one row of every card.
    static func columns(width: CGFloat, minimum: CGFloat, spacing: CGFloat, count: Int) -> Int {
        guard width.isFinite else { return max(1, count) }
        return max(1, Int(((width + spacing) / (max(minimum, 1) + spacing)).rounded(.down)))
    }

    /// Each row's height is its tallest card's.
    static func rowHeights(_ heights: [CGFloat], columns: Int) -> [CGFloat] {
        stride(from: 0, to: heights.count, by: max(1, columns)).map { start in
            heights[start..<min(start + max(1, columns), heights.count)].max() ?? 0
        }
    }

    private func metrics(width: CGFloat, subviews: Subviews) -> (columns: Int, column: CGFloat, rows: [CGFloat]) {
        let columns = Self.columns(width: width, minimum: minimum, spacing: spacing, count: subviews.count)
        let column = width.isFinite ? max(0, (width - spacing * CGFloat(columns - 1)) / CGFloat(columns)) : minimum
        let heights = subviews.map { $0.sizeThatFits(ProposedViewSize(width: column, height: nil)).height }
        return (columns, column, Self.rowHeights(heights, columns: columns))
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let count = CGFloat(subviews.count)
        let width = proposal.width ?? (count * minimum + max(0, count - 1) * spacing)
        let m = metrics(width: width, subviews: subviews)
        let height = m.rows.reduce(0, +) + spacing * CGFloat(max(0, m.rows.count - 1))
        let used = CGFloat(m.columns) * m.column + spacing * CGFloat(max(0, m.columns - 1))
        return CGSize(width: width.isFinite ? width : used, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let m = metrics(width: bounds.width, subviews: subviews)
        var y = bounds.minY
        for (row, height) in m.rows.enumerated() {
            for col in 0..<m.columns {
                let index = row * m.columns + col
                guard index < subviews.count else { break }
                subviews[index].place(at: CGPoint(x: bounds.minX + CGFloat(col) * (m.column + spacing), y: y),
                                      anchor: .topLeading, proposal: ProposedViewSize(width: m.column, height: height))
            }
            y += height + spacing
        }
    }
}

/// R-AG14 — the "leaves your Mac" sentence under the engine cards: a glyph that points out of the
/// box, the lead sentence in medium weight, the rest regular, all secondary text. Shared by
/// Settings → Engines and `.compact` (phase B's Who reads inherits it).
struct LeavesMacNoteRow: View {
    let note: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
            Image(systemName: "arrow.up.forward.square")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .accessibilityHidden(true)
            Text(styled)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private var styled: AttributedString {
        var text = AttributedString(note)
        if let lead = text.range(of: Copy.leavesMacLead) {
            text[lead].font = CicadaTheme.font(size: 11, weight: .medium)
        }
        return text
    }
}
