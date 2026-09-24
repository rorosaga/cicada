import SwiftUI

/// What the entity card knows about its own provenance payload.
enum ProvenanceSectionState {
    case loading
    case loaded(EntityProvenance)
    /// 404 — a backend without the route (or the page vanished). The section
    /// hides rather than show an error for a feature the server lacks (R10).
    case unavailable
    case failed

    var value: EntityProvenance? {
        if case let .loaded(p) = self { return p }
        return nil
    }

    init(_ load: ProvenanceLoad<EntityProvenance>) {
        switch load {
        case let .loaded(p): self = .loaded(p)
        case .gone: self = .unavailable
        case .failed: self = .failed
        }
    }
}

/// "Where this came from" (G118 slice 2, design §4.5): who wrote this page's
/// beliefs, the conversations that fed it with the best sentence from each,
/// and how many beliefs carry an exact quote. At the bottom of the Content
/// tab and always present — the owner asked for contribution to be EASY to
/// see ("easier and more friendly design to show who contributed to what
/// memory", 2026-09-23), not a tab away.
struct WhereThisCameFromSection: View {
    let entityId: String
    let state: ProvenanceSectionState

    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @State private var showAll = false
    /// Rows hover by fill, never a lift (DR-48, DS-3a).
    @State private var hoveredRow: String?

    var body: some View {
        switch state {
        case .unavailable:
            EmptyView()
        default:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                SectionLabel(Copy.Provenance.whereThisCameFrom)
                content
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            VStack(alignment: .leading, spacing: 6) {
                ForEach(0..<2, id: \.self) { i in
                    RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                        .fill(CicadaTheme.surfaceHover)
                        .frame(width: CicadaTheme.scaled(i == 1 ? 180 : 300), height: CicadaTheme.scaled(9))
                }
            }
            .accessibilityHidden(true)
        case .failed:
            Text(Copy.Provenance.unavailable)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        case .unavailable:
            EmptyView()
        case let .loaded(p):
            loaded(p)
        }
    }

    private func loaded(_ p: EntityProvenance) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(ProvenanceSummary.conversationsSentence(p))
                if let writers = ProvenanceSummary.writersSentence(p) { Text(writers) }
            }
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)

            if !p.contributors.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(p.contributors) { c in contributorChip(c) }
                }
            }

            let rows = showAll ? p.conversations
                               : Array(p.conversations.prefix(ProvenanceSummary.visibleConversations))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(rows) { row in conversationRow(row) }
            }
            if p.conversations.count > ProvenanceSummary.visibleConversations {
                Button(showAll ? Copy.Provenance.showFewerConversations
                               : Copy.Provenance.showAllConversations(p.conversations.count)) {
                    showAll.toggle()
                }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
            }

            let also = ProvenanceSummary.alsoItems(p)
            if !also.isEmpty {
                Text(also.joined(separator: "   ·   "))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(ProvenanceSummary.coverage(p.totals))
                if let legacy = ProvenanceSummary.legacyNote(p.totals) { Text(legacy) }
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: Contributors

    /// One author, with the face the contributors strip gives them. No share
    /// bar here — the Sources strip owns the one volume chart (§4.5).
    private func contributorChip(_ c: ProvenanceContributor) -> some View {
        HStack(spacing: 6) {
            ContributorAvatar(author: c.author, kind: c.kind, provider: c.provider, size: CicadaTheme.scaled(18))
            VStack(alignment: .leading, spacing: 0) {
                Text(ProvenanceSummary.chipName(c))
                    .font(CicadaTheme.font(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(ProvenanceSummary.chipCount(c))
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.leading, 4)
        .padding(.trailing, 10)
        .padding(.vertical, 4)
        .background(CicadaTheme.surfaceHover)
        .clipShape(Capsule())
        // What the two numbers count (§4.5 item 2), in plain words — never
        // the raw author id or "commit".
        .help(c.kind == "unknown" ? Copy.Provenance.beforeProvenanceHelp
                                  : Copy.Provenance.contributorHelp(ProvenanceSummary.sentenceName(c)))
        .accessibilityElement(children: .combine)
    }

    // MARK: Conversations

    private func conversationRow(_ row: ProvenanceConversation) -> some View {
        let title = row.title.isEmpty ? Copy.Provenance.untitled : row.title
        let day = ReaderTime.day(timestamp: row.timestamp, episode: row.episodeId, withYear: false)
        return Button {
            open(row)
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    OriginMark(origin: ReaderHeader.markOrigin(harness: row.harness, origin: row.origin),
                               size: CicadaTheme.scaled(16))
                        .iconHover()
                    Text(title)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let day {
                        Text(day).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(Copy.Provenance.beliefs(row.claimCount))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    if row.available {
                        Image(systemName: "chevron.right")
                            .font(CicadaTheme.font(size: 9, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                if !row.available {
                    Text(Copy.Provenance.notInBank)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                } else if let best = row.best, !best.excerpt.isEmpty {
                    bestQuote(best, row: row)
                }
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hoveredRow == row.id ? CicadaTheme.bgHover : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { inside in hoveredRow = inside ? row.id : (hoveredRow == row.id ? nil : hoveredRow) }
        .disabled(!row.available || router == nil)
        .accessibilityLabel([title, ProvenanceSummary.placeName(harness: row.harness, origin: row.origin),
                             day ?? "", Copy.Provenance.beliefs(row.claimCount)]
                                .filter { !$0.isEmpty }.joined(separator: ", ")
                            + (row.available ? ". \(Copy.Provenance.opensTheConversation)" : "."))
    }

    /// The best sentence (R-PB8) with its honest label: who said it for an
    /// asserted quote, "Mentioned here" + "Found by searching the
    /// conversation" for a derived one, and no emphasis at all when stale.
    private func bestQuote(_ best: ProvenanceSpan, row: ProvenanceConversation) -> some View {
        let parts = QuoteBlock.parts(excerpt: best.excerpt, mentionOffsets: best.mentionOffsets)
        let style: QuoteBlock.Style = best.stale ? .plain : (best.derived ? .bold : .wash)
        let caption: String = best.stale ? Copy.Provenance.staleCaption
            : (best.derived ? Copy.Provenance.derivedCaption : Copy.Provenance.quotedCaption)
        return QuoteBlock(before: parts.before, span: parts.span, after: parts.after, kind: best.displayKind,
                          label: EvidenceLabel.speaker(kind: best.displayKind,
                                                       agent: EvidenceSpeaker.agentName(harness: row.harness,
                                                                                         origin: row.origin)),
                          caption: caption, style: style, lineLimit: 4)
    }

    private func open(_ row: ProvenanceConversation) {
        guard row.available, let router else { return }
        let target = row.best.map {
            ReaderTarget.best($0, subjectId: entityId, knownTitle: row.title, knownHarness: row.harness)
        } ?? ReaderTarget(episode: row.episodeId, focus: .mention(entityId: entityId), subjectId: entityId,
                          knownTitle: row.title, knownHarness: row.harness)
        router.open(target)
    }
}
