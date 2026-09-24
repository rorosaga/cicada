import AppKit
import SwiftUI

/// F-12 (G146 plan R-PE16) — mock C's top of a person's card: the picture at 88 pt (a button: pick, drop, right-click),
/// the name in the display face at 24 (C-09 had 28, R-09 22 — 24 keeps the display role and matches Home's headline),
/// the Summary as a two-line standfirst, where the picture came from, and the facts strip.
struct PersonHero: View {
    let entity: Entity
    let summary: String?
    let isStub: Bool
    let inputs: PictureInputs?
    let facts: [PersonFact]
    var onOpenEntity: ((String) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingLG) {
                EntityPicture(id: entity.id, name: entity.name, type: .person, size: 88, held: entity.pictureRef,
                              heldInputs: inputs, editing: .hero)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                    Text(entity.isOwner ? Copy.Graph.ownerName(entity.name) : entity.name)
                        .font(CicadaTheme.displayFont(size: 24))
                        .tracking(CicadaTheme.displayTracking(size: 24))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    if let summary { EntitySummaryText(text: summary, isStub: isStub, lineLimit: 2) }
                    PictureSourceLine(id: entity.id, name: entity.name, type: .person, held: entity.pictureRef,
                                      inputs: inputs)
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
        let words = HStack(spacing: CicadaTheme.scaled(5)) {
            if let type = fact.valueType {
                Circle().fill(CicadaTheme.entityColor(for: type))
                    .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
            }
            Text(fact.value)
                .font(CicadaTheme.font(size: 13, weight: .medium))
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

/// F-12 / R-PE15 — where the picture came from, in words, and what can be done about it: "Photo from your Contacts ·
/// Use initials instead". `quietWhenEmpty` (the lighter header) shows nothing on a page with no picture.
struct PictureSourceLine: View {
    let id: String
    let name: String
    let type: EntityType
    let held: EntityPictureRef?
    let inputs: PictureInputs?
    var quietWhenEmpty = false

    @Environment(Store.self) private var store

    var body: some View {
        let current = store.picture(for: id, held: held)
        let resolvedInputs = store.pictureInputs(for: id, held: inputs)
        let detected = resolvedInputs.flatMap { EntityPictureResolver.detected(id: id, $0) }
        let options = PictureMenuModel.options(current: current, detected: detected).filter { $0 != .change }
        if current != nil || !quietWhenEmpty {
            HStack(spacing: CicadaTheme.scaled(6)) {
                if current?.source == .contacts { ContactsMark(size: 14) }
                if current != nil {
                    Text(Copy.People.sourceLine(current?.source))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(Array(options.enumerated()), id: \.element) { index, option in
                    if current != nil || index > 0 {
                        Text(Copy.People.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    InlineLink(title: Copy.People.optionLabel(option)) {
                        PictureActions.run(option, id: id, name: name, type: type, store: store, inputs: resolvedInputs)
                    }
                }
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
