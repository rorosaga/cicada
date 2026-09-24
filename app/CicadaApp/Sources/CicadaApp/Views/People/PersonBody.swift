import SwiftUI

/// F-12 — a section label led by a 12 pt glyph in a data hue, the same key on every card (seal · nodes · flag).
struct GlyphSectionLabel: View {
    let glyph: String
    let type: EntityType
    let text: String

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Image(systemName: glyph)
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.entityColor(for: type))
                .accessibilityHidden(true)
            SectionLabel(text)
        }
    }
}

/// R-PE18 — "· Written by [mark] Claude Code · Opus 5.5 · high effort · Sep 24", after the evidence chip.
struct SignedLineView: View {
    let claim: Claim

    var body: some View {
        if let who = SignedLine.who(claim) {
            HStack(spacing: CicadaTheme.scaled(4)) {
                Text(Copy.People.dot)
                Text(Copy.People.writtenByPrefix)
                switch SignedLine.mark(claim) {
                case .origin(let origin): OriginMark(origin: origin, size: CicadaTheme.scaled(12))
                case .logo(let name): LogoImage(name: name, size: CicadaTheme.scaled(12))
                case .bare: EmptyView()
                }
                Text([who, SignedLine.day(claim)].compactMap { $0 }.joined(separator: " · "))
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
            .help(BeliefWords.help(claim))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(SignedLine.text(claim) ?? who)
        }
    }
}

/// F-12 — "What Cicada believes · N, newest first": four signed rows, then "Show N more".
struct PersonBeliefsSection: View {
    let claims: [Claim]
    var onOpenTimeline: (Claim) -> Void = { _ in }
    @State private var showAll = false

    var body: some View {
        let ordered = PersonBeliefs.ordered(claims)
        if !ordered.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack {
                    GlyphSectionLabel(glyph: "checkmark.seal", type: .concept, text: Copy.People.believes(ordered.count))
                    Spacer(minLength: 0)
                    Text(Copy.People.newestFirst).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    ForEach(showAll ? ordered : Array(ordered.prefix(PersonBeliefs.collapsed))) { claim in
                        BeliefRow(claim: claim, onOpenTimeline: { onOpenTimeline(claim) }, signed: true)
                    }
                }
                .padding(.horizontal, -CicadaTheme.scaled(10))
                if !showAll, ordered.count > PersonBeliefs.collapsed {
                    TextButton(title: Copy.People.showMore(ordered.count - PersonBeliefs.collapsed)) {
                        Instant.run { showAll = true }
                    }
                    .padding(.leading, -CicadaTheme.scaled(10))
                }
            }
        }
    }
}

/// F-12 / R-PE17 — "How you know <name>": the person's picture at the centre, up to six neighbours around it on neutral
/// wells with hue rings, each a button into its card; one plain sentence and "Show on the graph ›" under it.
struct PersonMapSection: View {
    let personId: String
    let name: String
    let navigate: (String) -> Void
    let showOnGraph: () -> Void

    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        let map = PersonMapLayout.make(personId: personId, nodes: graphVM.nodes, edges: graphVM.edges)
        if !map.nodes.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                GlyphSectionLabel(glyph: "point.3.connected.trianglepath.dotted", type: .hub,
                                  text: Copy.People.howYouKnow(name))
                GeometryReader { geo in
                    ZStack {
                        Canvas { context, size in
                            let centre = CGPoint(x: size.width / 2, y: size.height / 2)
                            for node in map.nodes {
                                var path = Path()
                                path.move(to: centre)
                                path.addLine(to: CGPoint(x: node.x * size.width, y: node.y * size.height))
                                context.stroke(path, with: .color(CicadaTheme.ring(.strong)), lineWidth: 1)
                            }
                        }
                        EntityPicture(id: personId, name: name, type: .person, size: 44)
                            .position(x: geo.size.width / 2, y: geo.size.height / 2)
                        ForEach(map.nodes) { node in
                            Button { navigate(node.id) } label: {
                                VStack(spacing: CicadaTheme.scaled(2)) {
                                    Circle()
                                        .strokeBorder(CicadaTheme.entityColor(for: node.type), lineWidth: CicadaTheme.scaled(1.5))
                                        .background(Circle().fill(CicadaTheme.bgFocus))
                                        .frame(width: CicadaTheme.scaled(10), height: CicadaTheme.scaled(10))
                                    Text(node.isOwner ? Copy.you : node.name)
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textSecondary)
                                    Text(node.label)
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                                .lineLimit(1)
                                .frame(maxWidth: CicadaTheme.scaled(110))
                            }
                            .buttonStyle(.cicadaPlain)
                            .help(Copy.People.openHelp(node.name))
                            .position(x: node.x * geo.size.width, y: node.y * geo.size.height)
                        }
                    }
                }
                .frame(height: CicadaTheme.scaled(200))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgOption))
                .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                HStack(spacing: CicadaTheme.scaled(4)) {
                    Text(Copy.People.connected(map.total))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    InlineLink(title: Copy.People.showOnGraph, action: showOnGraph)
                }
            }
        }
    }
}

/// F-12 / R-PE19 — "What's happening", in the Projects band's grammar, from the Projects page's own cache.
struct PersonHappeningsSection: View {
    let personId: String
    let projectIds: [String]

    @Environment(ProjectsCache.self) private var cache
    @Environment(AppRouter.self) private var router

    var body: some View {
        let today = ISODay.today()
        let timelines = projectIds.compactMap { cache.display($0) }
        let rows = PersonHappenings.rows(personId: personId, timelines: timelines)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if !rows.isEmpty {
                HStack {
                    GlyphSectionLabel(glyph: EntityPictureLayout.glyph(.project), type: .project,
                                      text: Copy.People.whatsHappening)
                    Spacer(minLength: 0)
                    if let first = timelines.first {
                        InlineLink(title: Copy.People.openProject(first.project.name)) {
                            router.routeToProject(first.project.id)
                        }
                    }
                }
                ForEach(rows) { row in HappeningRow(row: row, today: today) }
            }
        }
        .task(id: projectIds) {
            for id in projectIds { await cache.refreshTimeline(id) }
        }
    }
}

private struct HappeningRow: View {
    let row: PersonHappening
    let today: ISODay

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(row.mark == .ongoing ? Copy.People.ongoing : RelativeDay.absolute(row.day, today: today))
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .help(RelativeDay.full(row.day))
                switch row.mark {
                case .planned:
                    Text(RelativeDay.distance(row.day, today: today))
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                case .ongoing:
                    Text(Copy.People.since(RelativeDay.absolute(row.day, today: today)))
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                case .done:
                    EmptyView()
                }
            }
            .frame(width: CicadaTheme.scaled(76), alignment: .leading)
            HappeningMark(mark: row.mark).padding(.top, CicadaTheme.scaled(4))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(row.text)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(2)
                if let origin = row.origin {
                    HStack(spacing: CicadaTheme.scaled(4)) {
                        OriginMark(origin: origin, size: CicadaTheme.scaled(12))
                        Text(OriginIconography.label(for: origin))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
        }
    }
}

/// The Projects band's marks (§3.8): a hollow diamond planned, a `progressFill` span ongoing, a neutral dot done.
private struct HappeningMark: View {
    let mark: PersonHappening.Mark

    var body: some View {
        Group {
            switch mark {
            case .planned:
                Image(systemName: "diamond").font(CicadaTheme.font(size: 10)).foregroundStyle(CicadaTheme.textSecondary)
            case .ongoing:
                Capsule().fill(CicadaTheme.progressFill)
                    .frame(width: CicadaTheme.scaled(12), height: CicadaTheme.scaled(3))
            case .done:
                Circle().fill(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
            }
        }
        .frame(width: CicadaTheme.scaled(12))
        .accessibilityHidden(true)
    }
}
