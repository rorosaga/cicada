import SwiftUI

// The owner's request (2026-09-23): "in the mascot page there should be a quick and easy way to
// change which model to use for consolidation." DESIGN_RULES §10 (Sleep), §9 2026-09-23.

/// Every decision the quick menu makes, as a value (`EngineQuickMenuTests`), so its views render.
///
/// **One source of truth (R-HS7).** It is built from `SleepEngineViewModel.response` — the object
/// `EngineChooser` (Settings → Engines) reads, over the same `GET/PUT /sleep/engine` — and a tap
/// writes through the same rule (`EngineWrite`). No second pref, no Store domain (Track E's
/// ruling 6), and no price or token: the wire models it reads carry none (2026-09-03).
struct EngineQuickMenuModel: Equatable {
    /// One engine: its card's label and state caption (`EngineOption`, R-E25), its real mark
    /// (DR-52), and whether a tap can choose it — a signed-out plan stays listed and says why.
    struct Row: Equatable, Identifiable {
        let id: String
        let label: String
        let caption: String
        let logo: String?
        let symbol: String
        let isSelected: Bool
        let isSelectable: Bool
        let help: String
    }

    /// One of the two ruling-4 lines (R-HS11).
    struct Preview: Equatable {
        let label: String
        let engine: String
        let text: String
        /// R-AG12 — the preview's model, so its `EngineMark` can tell OpenRouter from the key card.
        var model: String? = nil
    }

    let rows: [Row]
    let modelLabel: String
    let models: [String]
    let selectedModel: String
    let note: String?
    let showsPlansAndKeysLink: Bool
    let command: String?
    let previews: [Preview]
    let showsRuling: Bool

    /// What the button says (R-HS8): the engine and model a cycle you start would run — the manual
    /// preview, in the card's own name — prefixed "Auto ·" while Auto is the choice. The retired
    /// "Runs on …" caption stated the same fact. `nil` until the preview is known (R-A7).
    static func buttonLabel(_ response: SleepEngineResponse?) -> String? {
        guard let response, let manual = response.preview?.manual else { return nil }
        let name = EngineOption.candidateId(forEngine: manual.engine, model: manual.model)
            .flatMap { id in response.candidates.first { $0.id == id }?.label }
            ?? Copy.engineLabel(manual.engine)
        let runs = "\(name) · \(manual.model)"
        return response.mode == "auto" ? "\(Copy.EngineMenu.autoPrefix) · \(runs)" : runs
    }

    static func from(_ response: SleepEngineResponse) -> EngineQuickMenuModel {
        // R-AG12 — rows are cards, so the selected CARD is current (OpenRouter and the API key are
        // both `byok`); a model pick below still writes `response.mode`.
        let current = response.selected
        let rows = response.candidates.map { candidate -> Row in
            let caption = EngineOption.caption(for: candidate)
            let selectable = EngineOption.isSelectable(candidate, selectedMode: current)
            return Row(id: candidate.id, label: candidate.label, caption: caption,
                       logo: EngineOption.logoName(for: candidate.id), symbol: EngineOption.symbol(for: candidate.id),
                       isSelected: candidate.id == current, isSelectable: selectable,
                       help: selectable ? "\(candidate.label) — \(caption)" : Copy.EngineMenu.signInFirst(candidate.label))
        }
        let chosen = response.candidates.first { $0.id == current }
        // R-HS10 — a model list only where the engine has one to pick from; Auto and the API key say
        // in the backend's own words how their model is decided.
        let pickable = ["agent", "codex", "local"].contains(current)
        let note: String? = (current == "auto" || current == "byok") ? chosen?.detail : nil
        let command = chosen.flatMap { $0.id == "local" ? OllamaGuideState.from(candidate: $0).command : nil }
        let previews: [Preview] = response.preview.map { p in
            [Preview(label: Copy.EngineMenu.whenYouStart, engine: p.manual.engine,
                     text: "\(EngineOption.previewName(engine: p.manual.engine, model: p.manual.model)) · \(p.manual.model)",
                     model: p.manual.model),
             Preview(label: Copy.EngineMenu.scheduledCycles, engine: p.scheduled.engine,
                     text: "\(EngineOption.previewName(engine: p.scheduled.engine, model: p.scheduled.model)) · \(p.scheduled.model)",
                     model: p.scheduled.model)]
        } ?? []
        return EngineQuickMenuModel(
            rows: rows,
            modelLabel: current == "auto" ? Copy.EngineMenu.howAutoPicks : Copy.EngineMenu.model,
            models: pickable ? (chosen?.models ?? []) : [],
            selectedModel: response.model,
            note: note,
            showsPlansAndKeysLink: current == "byok",
            command: command,
            previews: previews,
            showsRuling: response.preview.map { $0.manual.engine != $0.scheduled.engine } ?? false)
    }
}

/// R-HS12 — one source for every engine line on the Sleep page: the chooser's response when it has
/// one (the echo of the newest write, from this menu or from Settings → Engines), else the page's
/// own load. Before this, a switch in Settings left the caption on the old engine until the next visit.
enum SleepEnginePreviewSource {
    static func current(chooser: SleepEngineResponse?, page: SleepEnginePreviews?) -> SleepEnginePreviews? {
        chooser?.preview ?? page
    }
}

/// The button beside Consolidate (R-HS8…R-HS10): a `NeutralButton` (DR-40) wearing the running
/// engine's mark, its name and model, and a disclosure glyph; it opens the menu below it. It owns
/// the menu's open state and the writes; `EngineQuickMenu` is a pure renderer.
struct EngineQuickMenuButton: View {
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @State private var open = false

    var body: some View {
        if let response = engineVM.response, let label = EngineQuickMenuModel.buttonLabel(response) {
            NeutralButton(title: label,
                          leading: AnyView(EngineMark(engine: response.preview?.manual.engine ?? "",
                                                      size: CicadaTheme.scaled(14),
                                                      model: response.preview?.manual.model)),
                          trailingSystemImage: "chevron.down",
                          help: Copy.EngineMenu.buttonHelp) { open.toggle() }
                .frame(maxWidth: CicadaTheme.scaled(EngineQuickMenu.buttonMaxWidth))
                .accessibilityLabel(Copy.EngineMenu.buttonAccessibility(label))
                .popover(isPresented: $open, arrowEdge: .bottom) {
                    // The fixed width lives HERE, not in the menu, so `EngineQuickMenuTests`
                    // can measure the menu unframed and catch a rigid child (DR-70).
                    EngineQuickMenu(model: .from(response), isSaving: engineVM.isSaving,
                                    writeFailed: engineVM.writeFailed,
                                    choose: choose, pickModel: pickModel, openSettings: openSettings)
                        .frame(width: CicadaTheme.scaled(EngineQuickMenu.width), alignment: .leading)
                }
        }
    }

    private func choose(_ id: String) {
        guard let response = engineVM.response,
              let candidate = response.candidates.first(where: { $0.id == id }),
              let write = EngineWrite.choosing(candidate, current: response.selected) else { return }
        apply(write)
    }

    private func pickModel(_ model: String) {
        guard let response = engineVM.response,
              let write = EngineWrite.model(model, mode: response.mode, current: response.model) else { return }
        apply(write)
    }

    private func apply(_ write: EngineWrite) {
        Task { @MainActor in
            await engineVM.apply(write)
            // R-E24 — the Plans & keys line follows the chosen engine, as after EngineChooser's write.
            await store.refresh([.connections])
        }
    }

    /// The popover is its own window: it closes before the panel opens, or it would float over it.
    private func openSettings(_ section: SettingsSection, _ row: SettingsRowID?) {
        open = false
        router.openSettings(section, row: row)
    }
}

/// The menu (the D-Sleep mock's `role="menu"`): the five engines, the chosen one's model, a
/// write failure in words, both ruling-4 lines, and a way to the full chooser. A pure renderer of
/// `EngineQuickMenuModel`; selection is a check and a neutral fill, never the accent (DR-5). It
/// fills the width it is offered; the popover offers `width` (`EngineQuickMenuButton`).
struct EngineQuickMenu: View {
    static let width: CGFloat = 360
    static let buttonMaxWidth: CGFloat = 300

    let model: EngineQuickMenuModel
    var isSaving = false
    var writeFailed = false
    let choose: (String) -> Void
    let pickModel: (String) -> Void
    let openSettings: (SettingsSection, SettingsRowID?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionLabel(Copy.EngineMenu.title)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.spacingXS)
            ForEach(model.rows) { row in
                EngineMenuRow(row: row, isSaving: isSaving) { choose(row.id) }
            }
            modelSection
            if writeFailed {
                Text(Copy.EngineMenu.writeFailed)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            previewsSection
            HStack {
                Spacer(minLength: 0)
                InlineLink(title: Copy.EngineMenu.moreInSettings) { openSettings(.engines, .engineChoice) }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.spacingXS)
        }
        .padding(CicadaTheme.scaled(6))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.bgMenu)
    }

    @ViewBuilder
    private var modelSection: some View {
        if !model.models.isEmpty || model.note != nil || model.command != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    SectionLabel(model.modelLabel)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if !model.models.isEmpty {
                        // R-HS10 — a native menu picker: rosters are the plan's own list, any length.
                        Picker(model.modelLabel, selection: Binding(get: { model.selectedModel },
                                                                    set: { pickModel($0) })) {
                            ForEach(model.models, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden()
                        .pickerStyle(.menu)
                        // If the fit test shows the pop-up keeping its intrinsic width for a long
                        // tag, pin it with `.frame(width:)` at the same 220 — never widen the menu.
                        .frame(maxWidth: CicadaTheme.scaled(220), alignment: .trailing)
                        .disabled(isSaving)
                    }
                }
                if let note = model.note {
                    Text(note)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.showsPlansAndKeysLink {
                    InlineLink(title: Copy.EngineMenu.plansAndKeys) { openSettings(.plansAndKeys, nil) }
                }
                if let command = model.command {
                    CommandBox(command: command)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.top, CicadaTheme.spacingSM)
        }
    }

    /// Ruling 4, visible (R-HS11): both lines always, each with its engine's mark; the sentence
    /// only when a scheduled cycle would run on something else.
    @ViewBuilder
    private var previewsSection: some View {
        if !model.previews.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(model.previews, id: \.label) { preview in
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        SectionLabel(preview.label)
                        HStack(spacing: CicadaTheme.scaled(6)) {
                            EngineMark(engine: preview.engine, size: CicadaTheme.scaled(12), model: preview.model)
                            Text(preview.text)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
                if model.showsRuling {
                    Text(Copy.scheduledNeverSpendsPlans)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.top, CicadaTheme.scaled(10))
            .padding(.bottom, CicadaTheme.spacingXS)
        }
    }
}

/// One engine (DR-48): its real mark (DR-52), the card's label, its state caption and a check on
/// the chosen one. A plan that is not signed in stays listed, dimmed, and says why in `.help`
/// (DR-41). Tertiary text on a fill steps to `textTertiaryOnFill` (DR-2).
private struct EngineMenuRow: View {
    let row: EngineQuickMenuModel.Row
    let isSaving: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                mark.frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
                Text(row.label)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(row.caption)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(row.isSelected || hovering ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                    .lineLimit(1)
                Image(systemName: "checkmark")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .opacity(row.isSelected ? 1 : 0)
                    .frame(width: CicadaTheme.scaled(14))
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(RowMetrics.menuItem))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(row.isSelected ? CicadaTheme.bgSelected
                                     : (hovering && row.isSelectable ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!row.isSelectable || isSaving)
        .opacity(row.isSelectable ? 1 : NeutralButton.disabledOpacity)
        .help(row.help)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(row.label), \(row.caption)")
        .accessibilityAddTraits(row.isSelected ? [.isSelected] : [])
    }

    /// The bare mark at 16 pt, as the preview lines' `EngineMark` draws it — not a `platformTile`,
    /// whose 0.6 inset would shrink it to under 10 pt. Clipped to the tile ratio's curvature
    /// (Track L: an opaque raster is never recut, the surface clips it; a no-op for every mark
    /// whose corners are already transparent).
    @ViewBuilder
    private var mark: some View {
        if let logo = row.logo {
            LogoImage(name: logo, size: CicadaTheme.scaled(16))
                .clipShape(CicadaTheme.shape(CicadaTheme.scaled(16) * 0.2))
        } else {
            Image(systemName: row.symbol)
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
