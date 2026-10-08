import SwiftUI

/// The entity column's header (Direction D, §10 Entity card; R-DG14 … R-DG16). Top to bottom: Back ⌘[ when the
/// trail has somewhere to go; the type as a `Tag` with its dot (DR-44), the status and confidence in words — or, for
/// a page whose newest source is over 90 days old, the status and "last mentioned <Mon YYYY>" (G194 A2) — and ×;
/// the logo and the name — the detail heading, in the display face (DR-16, DR-17); the page's Summary, links
/// still tappable; then the text tabs with counts (DR-45). It replaced tinted capsules, a confidence bar with a
/// bare "%", a 40 pt logo and underline tabs.
///
/// F-12 (G146 R-PE16): a person opens with `PersonHero`; every other type keeps this header with a 40 pt
/// `EntityPicture` and its source line when it has a picture.
struct EntityCardHeader: View {
    let entity: Entity
    let summary: String?
    let isStub: Bool
    let canGoBack: Bool
    let backTargetName: String?
    let onBack: () -> Void
    let showsClose: Bool
    let onClose: () -> Void
    let tabs: [TextTab<EntityCardTab>]
    @Binding var selection: EntityCardTab
    /// Units — the column's 28, the Clusters card's 16 (`EntityCardStyle.inset`).
    var inset: CGFloat = 28
    /// F-12 — a person's facts strip; empty for every other type.
    var facts: [PersonFact] = []
    /// C11 — the page's rung inputs, for the picture's menu and source line.
    var pictureInputs: PictureInputs? = nil
    /// "Show on the graph" — the card style only; on the Graph the node is already beside it.
    var onShowOnGraph: (() -> Void)? = nil
    /// A fact that names a page opens it (the card's wikilink navigation).
    var onOpenEntity: ((String) -> Void)? = nil
    /// G194 A2 — the day an old page is measured against; `nil` is the viewer's today, read at render (DR-58).
    /// Only tests and review renders pin it.
    var today: ISODay? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if canGoBack {
                TextButton(title: Copy.Graph.backTo(backTargetName), keyHint: "⌘[", help: Copy.Graph.backHelp(backTargetName),
                           action: onBack)
                    .keyboardShortcut("[", modifiers: .command)
                    .lineLimit(1)
                    .padding(.leading, -CicadaTheme.scaled(10))
                    .padding(.bottom, CicadaTheme.scaled(6))
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Tag(text: entity.type.label, dot: CicadaTheme.entityColor(for: entity.type))
                Text(EntityHeaderWords.statusLine(status: entity.status, confidence: entity.confidence,
                                                  lastReferenced: entity.lastReferenced, today: today ?? .today()))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .help(EntityHeaderWords.statusHelp(status: entity.status, confidence: entity.confidence,
                                                       lastReferenced: entity.lastReferenced, today: today ?? .today()))
                Spacer(minLength: 0)
                if let onShowOnGraph {
                    IconButton(systemName: "point.3.connected.trianglepath.dotted", help: Copy.People.showOnGraphHelp,
                               action: onShowOnGraph)
                }
                if showsClose {
                    IconButton(systemName: "xmark", help: Copy.Graph.closeHelp(entity.name), action: onClose)
                }
            }
            .frame(minHeight: CicadaTheme.scaled(28))
            if entity.type == .person {
                PersonHero(entity: entity, summary: summary, isStub: isStub, inputs: pictureInputs, facts: facts,
                           onOpenEntity: onOpenEntity)
                    .padding(.top, CicadaTheme.spacingMD)
            } else {
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 40, held: entity.pictureRef,
                                  heldInputs: pictureInputs, editing: .tile)
                    // Wraps rather than truncates: a selectable name cut short opened over the Summary on a click.
                    Text(entity.isOwner ? Copy.Graph.ownerName(entity.name) : entity.name)
                        .font(CicadaTheme.displayFont(size: 22))
                        .tracking(CicadaTheme.displayTracking(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, CicadaTheme.spacingSM)
                if let summary {
                    EntitySummaryText(text: summary, isStub: isStub).padding(.top, CicadaTheme.scaled(6))
                }
                PictureSourceLine(id: entity.id, name: entity.name, type: entity.type, held: entity.pictureRef,
                                  inputs: pictureInputs, quietWhenEmpty: true)
                    .padding(.top, CicadaTheme.scaled(4))
            }
            TextTabs(tabs: tabs, selection: Binding(get: { selection }, set: { if let tab = $0 { selection = tab } }))
                .padding(.top, CicadaTheme.spacingLG)
                .padding(.leading, -CicadaTheme.scaled(TextTabs<EntityCardTab>.horizontalPadding))
        }
        .padding(.top, CicadaTheme.scaled(14))
        .padding(.leading, CicadaTheme.scaled(inset))
        .padding(.trailing, CicadaTheme.scaled(20))
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// R-DG15 — the Summary as inline markdown (wikilinks tappable through the card's `.wikilinkNavigation`); a stub's
/// preview as clean text (DR-56), two lines at most. The person hero caps a full one at two lines too (F-12's
/// standfirst): a click shows all of it and the header grows to fit; "Show less" folds it back.
///
/// A capped Summary is never selectable. A selectable `Text` is an AppKit field; clicking it opened a field editor that
/// showed the whole Summary at its own height, outside the layout — over the picture line and the facts strip, with a
/// selection highlight on top (owner, 2026-10-08). Selectable only when it shows all of itself (`HeaderOverlapTests`).
struct EntitySummaryText: View {
    let text: String
    let isStub: Bool
    var lineLimit: Int? = nil
    @State private var expanded: Bool

    init(text: String, isStub: Bool, lineLimit: Int? = nil, expanded: Bool = false) {
        self.text = text
        self.isStub = isStub
        self.lineLimit = lineLimit
        _expanded = State(initialValue: expanded)
    }

    var body: some View {
        if isStub {
            Text(ExcerptText.clean(text))
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(2)
        } else if let lineLimit, !expanded {
            Text(MarkdownBody.inlineAttributed(text))
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(lineLimit)
                .fixedSize(horizontal: false, vertical: true)
                .contentShape(Rectangle())
                .onTapGesture { Instant.run { expanded = true } }
                .help(Copy.Graph.showWholeSummary)
                .accessibilityAddTraits(.isButton)
                .accessibilityHint(Copy.Graph.showWholeSummary)
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(MarkdownBody.inlineAttributed(text))
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                if lineLimit != nil {
                    TextButton(title: Copy.Graph.showLess) { Instant.run { expanded = false } }
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
            }
        }
    }
}
