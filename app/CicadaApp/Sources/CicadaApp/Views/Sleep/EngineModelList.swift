import SwiftUI

/// Engine picker v2 (ruling 48 part 11; `docs/design/redesign-2026-10-28/10-engine-picker-*.png`): the chosen card's
/// models as a filterable list, replacing the native model `Picker` (amends R-HS10). Every decision is a value
/// (`EnginePickerV2Tests`); `EngineModelList` only draws it.
///
/// - **Families** come from the backend's catalogue (`model_catalogue.ordered`): headings in the order the harness
///   first lists them, newest first inside each. The first `shownPerFamily` of a family show; the rest wait behind
///   *Show N older*. A filter shows every match.
/// - **New** is a `Tag` (DR-44) on a model first seen within 14 days (`catalogue.new`, computed by the backend).
/// - **Freshness in words:** whose list it is and how old, with Refresh — a re-read of the harness on this click only
///   (the page never probes, ruling 46). A harness whose format changed says so (`catalogue.drift`).
/// - A model's list price rides its row only where the wire carries one (the key cards; ruling 12's engine menu).
struct EngineModelListModel: Equatable {
    static let shownPerFamily = 3

    struct Row: Equatable, Identifiable {
        let id: String
        let price: String?
        let isNew: Bool
        let isSelected: Bool
        /// "Last run on <id>" when an alias resolved on a real run — `.help` only.
        let help: String?
        /// Ruling 46a — "Billed separately at list price" on a model the tool bills outside the plan, on the row
        /// itself so it is read before the model is chosen.
        var billing: String? = nil
    }

    struct Section: Equatable, Identifiable {
        let id: String
        let label: String
        let total: Int
        let rows: [Row]
        let hidden: Int
    }

    let cardId: String
    let sections: [Section]
    let total: Int
    let freshness: String
    let drift: String?
    let canRefresh: Bool

    /// The rows in the order the keys walk them.
    var flat: [Row] { sections.flatMap(\.rows) }

    static func from(card: SleepEngineCandidate, selected: String, prices: [String: String] = [:], filter: String = "",
                     expanded: Set<String> = [], now: Date = Date()) -> EngineModelListModel {
        let catalogue = card.catalogue
        // The catalogue's rows (grouped, newest first); an older backend's bare `models` as one unnamed family.
        let entries: [ModelCatalogue.Model] = catalogue.map { $0.models } ?? card.models.map {
            ModelCatalogue.Model(id: $0, source: "harness")
        }
        let query = filter.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var order: [String] = []
        var groups: [String: [ModelCatalogue.Model]] = [:]
        var labels: [String: String] = [:]
        for entry in entries {
            let key = entry.family
            if groups[key] == nil { order.append(key) }
            groups[key, default: []].append(entry)
            labels[key] = entry.familyLabel
        }
        let sections: [Section] = order.compactMap { key in
            let all = groups[key] ?? []
            let matching = query.isEmpty ? all : all.filter {
                $0.id.lowercased().contains(query) || $0.familyLabel.lowercased().contains(query)
            }
            guard !matching.isEmpty else { return nil }
            let cap = query.isEmpty && !expanded.contains(key) ? shownPerFamily : Int.max
            var shown = Array(matching.prefix(cap))
            // The chosen model is always on screen, even when it is an older one.
            if let chosen = matching.first(where: { $0.id == selected }), !shown.contains(chosen) { shown.append(chosen) }
            let rows = shown.map { m in
                Row(id: m.id, price: prices[m.id], isNew: m.new, isSelected: m.id == selected,
                    help: m.billingNote ?? m.resolvesTo.map(Copy.EngineMenu.resolvesTo),
                    billing: m.billingNote == nil ? nil : Copy.EngineMenu.billedSeparately)
            }
            return Section(id: key, label: labels[key] ?? "", total: all.count, rows: rows,
                           hidden: matching.count - shown.count)
        }
        let own = catalogue.map { ["harness", "claude --help"].contains($0.source) || $0.source.hasSuffix(" models")
            || $0.source == "model/list" || $0.source == "ollama tags" } ?? true
        let age = catalogue?.asOf.flatMap(Self.date(iso:)).map { Copy.EngineMenu.age(seconds: max(0, now.timeIntervalSince($0))) }
        return EngineModelListModel(
            cardId: card.id, sections: sections, total: entries.count,
            freshness: Copy.EngineMenu.freshness(card: card.label, own: own, age: own ? age : nil),
            drift: catalogue?.drift, canRefresh: own && card.connected)
    }

    /// One formatter per shape, made once (a formatter costs more to make than the whole list to group).
    private static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func date(iso: String) -> Date? {
        isoPlain.date(from: iso) ?? isoFractional.date(from: iso)
    }

    /// ↑/↓ from the filter: the next row's id, wrapping at neither end.
    func step(from current: String?, by delta: Int) -> String? {
        let ids = flat.map(\.id)
        guard !ids.isEmpty else { return nil }
        guard let current, let at = ids.firstIndex(of: current) else { return delta > 0 ? ids.first : ids.last }
        return ids[min(max(at + delta, 0), ids.count - 1)]
    }
}

/// The list itself: the filter (focused on open, DR-46), each family under a `SectionLabel` with its count, rows with
/// a check on the chosen one and a "New" `Tag`, *Show N older*, then whose list it is and how old, with Refresh. A
/// keyboard choice never animates (DR-60).
struct EngineModelList: View {
    let card: SleepEngineCandidate
    let selected: String
    var prices: [String: String] = [:]
    var isSaving = false
    var refreshing = false
    var refreshFailed = false
    let pick: (String) -> Void
    let refresh: () -> Void

    @State private var filter = ""
    @State private var expanded: Set<String> = []
    @State private var highlighted: String?

    private var model: EngineModelListModel {
        .from(card: card, selected: selected, prices: prices, filter: filter, expanded: expanded)
    }

    var body: some View {
        let list = model
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            CicadaSearchField(text: $filter, prompt: Copy.EngineMenu.filterPlaceholder(list.total), findEnabled: false,
                              autofocus: true,
                              onSubmit: { if let id = highlighted ?? list.flat.first?.id { pick(id) } },
                              onMove: { delta in highlighted = list.step(from: highlighted, by: delta) })
            if let drift = list.drift {
                Text(drift)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if list.sections.isEmpty {
                        Text(Copy.EngineMenu.noMatch)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.vertical, CicadaTheme.spacingXS)
                    }
                    ForEach(list.sections) { section in
                        VStack(alignment: .leading, spacing: 0) {
                            if !section.label.isEmpty {
                                SectionLabel("\(section.label) · \(section.total)")
                                    .padding(.top, CicadaTheme.spacingXS)
                                    .padding(.bottom, CicadaTheme.scaled(2))
                            }
                            ForEach(section.rows) { row in
                                ModelRow(row: row, highlighted: row.id == highlighted, disabled: isSaving) { pick(row.id) }
                            }
                            if section.hidden > 0 {
                                InlineLink(title: Copy.EngineMenu.showOlder(section.hidden)) {
                                    var t = Transaction()
                                    t.disablesAnimations = true
                                    withTransaction(t) { _ = expanded.insert(section.id) }
                                }
                                .padding(.vertical, CicadaTheme.scaled(4))
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: CicadaTheme.scaled(360))
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(refreshFailed ? Copy.EngineMenu.refreshFailed : refreshing ? Copy.EngineMenu.refreshing : list.freshness)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.spacingSM)
                if list.canRefresh {
                    TextButton(title: Copy.EngineMenu.refresh, help: Copy.EngineMenu.refreshHelp, inline: true,
                               action: refresh)
                        .disabled(refreshing)
                }
            }
            .padding(.top, CicadaTheme.spacingXS)
        }
    }
}

/// One model: its id (the person's own choice, so named), "New" as a `Tag`, a list price where the wire gives one,
/// a check on the chosen one. Selection is a neutral fill and a check, never the accent (DR-5).
private struct ModelRow: View {
    let row: EngineModelListModel.Row
    let highlighted: Bool
    let disabled: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(row.id)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                if row.isNew { Tag(text: Copy.EngineMenu.new) }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let billing = row.billing {
                    Text(billing)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(row.isSelected || hovering ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
                if let price = row.price {
                    Text(price)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(row.isSelected || hovering ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
                Image(systemName: "checkmark")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .opacity(row.isSelected ? 1 : 0)
                    .frame(width: CicadaTheme.scaled(14))
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(RowMetrics.menuItem))
            .rowHoverFill(hovering: hovering || highlighted, selected: row.isSelected)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(disabled)
        .help(row.help ?? row.id)
        .onHover { hovering = $0 }
        .accessibilityLabel(row.isNew ? "\(row.id), \(Copy.EngineMenu.new)" : row.id)
        .accessibilityAddTraits(row.isSelected ? [.isSelected] : [])
    }
}
