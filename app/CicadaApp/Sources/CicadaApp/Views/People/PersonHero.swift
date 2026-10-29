import AppKit
import SwiftUI

/// F-12 (G146 plan R-PE16) — mock C's top of a person's card: the picture at 88 pt (a button: pick, drop, right-click),
/// the name in the display face at 24 (C-09 had 28, R-09 22 — 24 keeps the display role and matches Home's headline),
/// the Summary as a two-line standfirst (a click shows all of it), where the picture came from, and the facts strip.
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
                    PictureSourceLine(id: entity.id, held: entity.pictureRef)
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

/// F-12 / R-PE15 — where the picture came from, in words: "Photo from your Contacts". Nothing on a page with no
/// picture. What can be done about it lives on the picture itself (owner 2026-10-29: "you change the picture by
/// pressing on the picture itself"; `PictureChoices`), never as blue words here.
struct PictureSourceLine: View {
    let id: String
    let held: EntityPictureRef?

    @Environment(Store.self) private var store

    var body: some View {
        if let current = store.picture(for: id, held: held) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                if current.source == .contacts { ContactsMark(size: 14) }
                Text(Copy.People.sourceLine(current.source))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .lineLimit(1)
        }
    }
}

/// R-PE7 — the Contacts app's own icon from this Mac (Track L's R-L1: an Apple mark is never committed), else its SF
/// Symbol. Becomes `OriginMark(origin: "contacts-local")` once T-Sources maps that origin.
struct ContactsMark: View {
    var size: CGFloat = 14

    var body: some View {
        let points = CicadaTheme.scaled(size)
        Group {
            if let icon = InstalledAppIcon.image(bundleId: "com.apple.AddressBook", size: points) {
                Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
            } else {
                Image(systemName: "person.crop.circle")
                    .font(CicadaTheme.font(size: size * 0.8))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .frame(width: points, height: points)
        .accessibilityHidden(true)
    }
}
