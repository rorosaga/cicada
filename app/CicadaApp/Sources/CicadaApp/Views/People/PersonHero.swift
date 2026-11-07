import AppKit
import SwiftUI

/// F-12 (G146 plan R-PE16) — mock C's top of a person's card: the picture at 88 pt (a button: pick, drop, right-click),
/// the name in the display face at 24 (C-09 had 28, R-09 22 — 24 keeps the display role and matches Home's headline),
/// the Summary as a two-line standfirst (a click shows all of it) and the facts strip. Where the picture came from is the
/// picture's own help, VoiceOver value and the first line of its menu — never a caption under the name (owner 2026-10-29).
struct PersonHero: View {
    let entity: Entity
    let summary: String?
    let isStub: Bool
    let inputs: PictureInputs?
    let facts: [PersonFact]
    var onOpenEntity: ((String) -> Void)? = nil
    /// Whether the Summary starts expanded (renders and tests; the card always starts folded).
    var summaryExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingLG) {
                EntityPicture(id: entity.id, name: entity.name, type: .person, size: 88, held: entity.pictureRef,
                              heldInputs: inputs, editing: .hero)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                    // Wraps rather than truncates: a selectable name cut short opened over what follows on a click.
                    Text(entity.isOwner ? Copy.Graph.ownerName(entity.name) : entity.name)
                        .font(CicadaTheme.displayFont(size: 24))
                        .tracking(CicadaTheme.displayTracking(size: 24))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    if let summary { EntitySummaryText(text: summary, isStub: isStub, lineLimit: 2, expanded: summaryExpanded) }
                }
            }
            if !facts.isEmpty { FactsStrip(facts: facts, onOpenEntity: onOpenEntity) }
        }
    }
}

/// F-12's facts strip on `bgOption` with a resting ring; the cells wrap to the column (DR-70), each a label, a value and
/// its compressed provenance line.
struct FactsStrip: View {
    let facts: [PersonFact]
    var onOpenEntity: ((String) -> Void)? = nil

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(128)), spacing: CicadaTheme.spacingMD,
                                     alignment: .topLeading)],
                  alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(facts) { fact in FactCell(fact: fact, onOpenEntity: onOpenEntity) }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgOption))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}

private struct FactCell: View {
    let fact: PersonFact
    let onOpenEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
            SectionLabel(fact.label)
            value
            if fact.line != nil || !fact.marks.isEmpty {
                HStack(spacing: CicadaTheme.scaled(4)) {
                    ForEach(fact.marks, id: \.self) { OriginMark(origin: $0, size: CicadaTheme.scaled(12)) }
                    if let line = fact.line {
                        Text(line)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var value: some View {
        if fact.values.count > 1 { values } else { single }
    }

    /// Several current values (a person's places, 2026-10-14): each its own page link, a dot between them, then
    /// "+N" in tertiary text whose help names the rest (DR-51, DR-56). One line; the type dots are left to a single value.
    private var values: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            ForEach(Array(fact.values.enumerated()), id: \.element.id) { index, item in
                if index > 0 {
                    Text(Copy.People.dot).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                valueWord(item)
            }
            if !fact.more.isEmpty {
                Text(Copy.People.more(fact.more.count))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(Copy.People.alsoAt(fact.more))
            }
        }
        .lineLimit(1)
    }

    @ViewBuilder
    private func valueWord(_ item: PersonFactValue) -> some View {
        let words = Text(item.name)
            .font(CicadaTheme.rowFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .lineLimit(1)
            .truncationMode(.tail)
        if let id = item.entity, let onOpenEntity {
            Button { onOpenEntity(id) } label: { words }
                .buttonStyle(.cicadaPlain)
                .help(Copy.People.openHelp(item.name))
        } else {
            words
        }
    }

    @ViewBuilder
    private var single: some View {
        let words = HStack(spacing: CicadaTheme.scaled(5)) {
            if let type = fact.valueType {
                Circle().fill(CicadaTheme.entityColor(for: type))
                    .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
            }
            Text(fact.value)
                .font(CicadaTheme.rowFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
        }
        if let id = fact.valueEntity, let onOpenEntity {
            Button { onOpenEntity(id) } label: { words }
                .buttonStyle(.cicadaPlain)
                .help(Copy.People.openHelp(fact.value))
        } else {
            words
        }
    }
}
