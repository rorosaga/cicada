import SwiftUI

/// "Where did this come from?" as one small control (G118 slice 2, design
/// §4.2/§4.3). Replaces the inert `EpisodePill` (A9) everywhere a claim is
/// shown. Rest the pointer on it: a preview of the exact words, with who
/// said them. Click (or Return): the Reader opens on that sentence.
///
/// Reads `ProvenanceRouter`/`ProvenanceCache` as OPTIONAL environment values:
/// hosted outside the main window (a preview, a test), it still renders and
/// still previews, it just has nowhere to open.
struct EvidenceChip: View {
    let model: EvidenceChipModel
    /// The entity whose belief this is — the Reader's navigator steps through
    /// its spans, and a legacy chip asks the server to find its name.
    let subjectId: String?

    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @Environment(\.evidenceDocIndex) private var index
    @State private var chipHovered = false
    @State private var previewHovered = false
    @State private var showPreview = false
    @State private var hoverTask: Task<Void, Never>?

    private var meta: EvidenceDocMeta? { index.meta(model.episode) }
    private var target: ReaderTarget? { model.target(subjectId: subjectId, meta: meta) }

    var body: some View {
        Button(action: open) { label }
            .buttonStyle(.cicadaPlain)
            .onHover { inside in
                chipHovered = inside
                pointer(inside: inside)
            }
            .onKeyPress(.space) {
                showPreview.toggle()
                return .handled
            }
            .popover(isPresented: $showPreview, arrowEdge: .top) {
                EvidencePreview(model: model, meta: meta, subjectId: subjectId,
                                onOpen: target == nil ? nil : open)
                    .onHover { inside in
                        previewHovered = inside
                        if !inside { pointer(inside: false) }
                    }
            }
            .accessibilityLabel(EvidenceLabel.accessibility(model, meta: meta, opens: target != nil && router != nil))
            .accessibilityAction(named: Copy.Provenance.previewQuote) { showPreview = true }
            .onDisappear { hoverTask?.cancel() }
    }

    private var label: some View {
        HStack(spacing: 4) {
            mark
            Text(EvidenceLabel.chipText(model, meta: meta))
                .font(CicadaTheme.font(size: 10, weight: .regular))
                .lineLimit(1)
        }
        .foregroundStyle(CicadaTheme.textSecondary)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(CicadaTheme.surfaceHover.opacity(0.6))
        .clipShape(Capsule())
        .overlay {
            // A derived chip is outlined dashed (§4.2): the same shape, visibly
            // not a quote. The label says "Mentioned here" either way.
            if model.kind == .derived {
                Capsule().strokeBorder(CicadaTheme.borderLight, style: StrokeStyle(lineWidth: 1, dash: [2, 2]))
            }
        }
        .contentShape(Capsule())
    }

    @ViewBuilder
    private var mark: some View {
        let size = CicadaTheme.scaled(11)
        if model.kind == .assistant,
           let agent = EvidenceSpeaker.agentOrigin(harness: meta?.harness, origin: meta?.origin) {
            // The label names this agent ("ChatGPT replied"), so its real mark
            // sits beside it — an import's vendor included.
            OriginMark(origin: agent, size: size)
        } else if model.kind == .page {
            LogoImage(entityId: model.episode, name: meta?.title ?? model.episode, type: .media, size: size)
        } else {
            Image(systemName: EvidenceLabel.symbol(model.kind))
                .font(CicadaTheme.font(size: 9, weight: .medium))
                .foregroundStyle(EvidenceLabel.ruleColor(model.kind))
                .iconHover(hovering: chipHovered)
        }
    }

    private func open() {
        hoverTask?.cancel()
        guard let target, let router else {
            showPreview = true
            return
        }
        showPreview = false
        router.open(target)
    }

    /// Dwell to open, grace to close (§4.2): the preview opens after
    /// `hoverPreviewDelay` on the chip and closes `hoverPreviewGrace` after the
    /// pointer leaves — unless it has moved into the preview itself.
    private func pointer(inside: Bool) {
        hoverTask?.cancel()
        hoverTask = Task { @MainActor in
            let wait = inside ? CicadaTiming.hoverPreviewDelay : CicadaTiming.hoverPreviewGrace
            try? await Task.sleep(for: .seconds(wait))
            guard !Task.isCancelled else { return }
            if inside {
                if chipHovered { showPreview = true }
            } else if !chipHovered && !previewHovered {
                showPreview = false
            }
        }
    }
}

/// The hover preview (§4.2): who said it, the words with their neighbourhood,
/// and a way into the whole conversation. Fetches lazily through
/// `ProvenanceCache` — `/span` for a stored span, `/text?focus=` for a legacy
/// mention — and never caches text anywhere but memory (spans, not copies).
struct EvidencePreview: View {
    let model: EvidenceChipModel
    let meta: EvidenceDocMeta?
    let subjectId: String?
    let onOpen: (() -> Void)?

    @Environment(ProvenanceCache.self) private var cache: ProvenanceCache?

    enum Phase: Equatable {
        case loading
        case quote(before: String, span: String, after: String, style: QuoteBlock.Style, note: String?)
        case note(String)
    }

    @State private var phase: Phase = .loading

    private static let context = 240

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: EvidenceLabel.symbol(model.kind))
                    .foregroundStyle(EvidenceLabel.ruleColor(model.kind))
                Text(headerLine)
                    .lineLimit(1)
            }
            .font(CicadaTheme.font(size: 11, weight: .medium))
            .foregroundStyle(CicadaTheme.textSecondary)

            switch phase {
            case .loading:
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(0..<3, id: \.self) { i in
                        RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                            .fill(CicadaTheme.surfaceHover)
                            .frame(width: CicadaTheme.scaled(i == 2 ? 160 : 300), height: CicadaTheme.scaled(8))
                    }
                }
                .accessibilityHidden(true)
            case let .quote(before, span, after, style, note):
                QuoteBlock(before: before, span: span, after: after, kind: model.kind,
                           label: nil, caption: caption(style), style: style)
                if let note {
                    Text(note)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            case let .note(text):
                Text(text)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let onOpen {
                HStack {
                    Spacer()
                    Button(action: onOpen) {
                        Label(Copy.Provenance.openConversation, systemImage: "chevron.right")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(360), alignment: .leading)
        .task(id: model.id) { await load() }
    }

    private var headerLine: String {
        var parts = [speakerLine]
        if let title = meta?.title, !title.isEmpty { parts.append(title) }
        if let day = ReaderTime.day(timestamp: nil, episode: model.episode, withYear: false) { parts.append(day) }
        return parts.joined(separator: " · ")
    }

    /// R-FA14 — the hover names the model the way the chip does, and is where
    /// an app with no capture says "model not shared by this app". A line that
    /// adds nothing to the agent's bare name (a pre-D1 Claude Code turn) keeps
    /// today's "Claude Code replied".
    private var speakerLine: String {
        let agent = EvidenceLabel.agent(meta)
        if model.kind == .assistant,
           let line = ModelNames.agentLine(agent: agent ?? (model.model == nil ? nil : Copy.Provenance.theAgent),
                                           harness: meta?.harness, model: model.model, effort: model.effort),
           line != agent {
            return line
        }
        return EvidenceLabel.speaker(kind: model.kind, agent: agent)
    }

    private func caption(_ style: QuoteBlock.Style) -> String? {
        switch style {
        case .wash: Copy.Provenance.quotedCaption
        case .bold: Copy.Provenance.derivedCaption
        case .plain: nil
        }
    }

    private func load() async {
        switch model.source {
        case let .stored(ev):
            guard ev.isSpan else {
                phase = .note(Copy.Provenance.inferred)
                return
            }
            guard let cache else { return }
            switch await cache.span(ev) {
            case let .loaded(span) where span.stale && span.text.isEmpty:
                // R-PU25 — the document no longer reaches this span: no words
                // to quote, and "couldn't open" would be untrue.
                phase = .note(Copy.Provenance.stale)
            case let .loaded(span):
                phase = .quote(before: span.before, span: span.text, after: span.after,
                               style: span.stale ? .plain : .wash,
                               note: span.stale ? Copy.Provenance.stale : (span.grown ? Copy.Provenance.grown : nil))
            case .gone:
                phase = .note(Copy.Provenance.gone)
            case .failed:
                phase = .note(Copy.Provenance.failed)
            }
        case let .mention(episode, subject):
            guard let cache else { return }
            switch await cache.document(episode: episode, focus: .mention(entityId: subject)) {
            case let .loaded(doc):
                guard let range = doc.focus?.range else {
                    phase = .note(Copy.Provenance.previewNotFound)
                    return
                }
                let parts = ScalarText(doc.text).around(range.lowerBound, range.upperBound, radius: Self.context)
                phase = .quote(before: parts.before, span: parts.span, after: parts.after, style: .bold, note: nil)
            case .gone:
                phase = .note(Copy.Provenance.gone)
            case .failed:
                phase = .note(Copy.Provenance.failed)
            }
        }
    }
}

/// A claim's evidence as a run of chips: the first `visibleLimit`, then
/// "+N more", which expands in place (plan R-PU10 — the chip lives inside
/// generic surfaces that cannot switch the card's tab).
struct EvidenceChipRun: View {
    let chips: [EvidenceChipModel]
    let subjectId: String?
    @Binding var expanded: Bool

    var body: some View {
        let shown = expanded ? chips : Array(chips.prefix(EvidenceLabel.visibleLimit))
        ForEach(shown) { chip in
            EvidenceChip(model: chip, subjectId: subjectId)
        }
        if chips.count > EvidenceLabel.visibleLimit {
            Button(expanded ? Copy.Provenance.fewerEvidence
                            : Copy.Provenance.moreEvidence(chips.count - EvidenceLabel.visibleLimit)) {
                expanded.toggle()
            }
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.font(size: 10, weight: .medium))
            .foregroundStyle(CicadaTheme.accent)
        }
    }
}
