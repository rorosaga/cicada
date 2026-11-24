import SwiftUI

// G245 (ruling 78, plan 3.2 item 2) — the Reads block of a source's page: a `SectionLabel` row with *Check now* at its
// trailing edge, then ONE soft block with a row per stream. A row is the stream's name and a quiet line (how it is read,
// how deep its items go), the count · last read (or the state word), and one control: the switch, or — for a stream
// that needs the source's own setup — nothing here, the source's connect step stands under the block.
//
// Applies DR-5 (no primary here: Check now is a compact neutral button), DR-9/DR-10 (a ring, no shadow), DR-34 (row
// heights from tokens), DR-37 (the block holds the group), DR-38 (a word said once), DR-47 (the section label), DR-59
// (one line, the whole on hover), DR-81 (a block with no stream is not drawn); the 2026-11-23 soft-card line.
// Value-driven (streams, results, closures): `SourcePageRenderTests` draws it from fixtures.

struct SourceReadsBlock: View {
    let streams: [ResolvedStream]
    var results: [String: SourceStreamCheckModel.Result] = [:]
    var checking: Set<String> = []
    /// A switch flipped and not yet answered: shown as flipped (optimistic), rolled back by the caller on a refusal.
    var pending: [String: Bool] = [:]
    var isChecking = false
    var checkedAt: Date?
    var failure: String?
    /// The compact page (onboarding's sheet) has no Check now.
    var showsCheck = true
    let now: Date
    let onToggle: (ResolvedStream, Bool) -> Void
    let onFix: (MacPermission) -> Void
    let onCheck: () -> Void

    var body: some View {
        if !streams.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                header
                VStack(spacing: 0) {
                    ForEach(Array(streams.enumerated()), id: \.element.id) { index, resolved in
                        if index > 0 { rowDivider }
                        SourceReadsRow(resolved: resolved, result: results[resolved.id],
                                       checking: checking.contains(resolved.id), pending: pending[resolved.id], now: now,
                                       onToggle: { onToggle(resolved, $0) }, onFix: onFix)
                    }
                }
                .padding(.vertical, CicadaTheme.spacingXS)
                .softCard(ground: .page, shape: .block, inset: .none, fillsWidth: true)
            }
        }
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            SectionLabel(Copy.Streams.reads)
            Spacer(minLength: CicadaTheme.spacingSM)
            if showsCheck {
                if let failure {
                    Text(failure).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning).lineLimit(1)
                } else if let checkedAt, !isChecking {
                    Text(Copy.Streams.checkedAgo(SourceCatalog.ago(checkedAt, now: now)))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                }
                NeutralButton(title: isChecking ? Copy.Streams.checkingConnections : Copy.Streams.checkNow,
                              size: .compact, isDisabled: isChecking, help: Copy.Streams.checkNowHelp, action: onCheck)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
    }

    /// A hairline between two rows of the block, inset like the rows' text (a ring, never a shadow).
    private var rowDivider: some View {
        Rectangle()
            .fill(CicadaTheme.ring(.resting))
            .frame(height: 1)
            .padding(.horizontal, CicadaTheme.scaled(14))
    }
}

/// One stream of a source: name and quiet line, then what it holds and how the last read went, then its control.
struct SourceReadsRow: View {
    let resolved: ResolvedStream
    var result: SourceStreamCheckModel.Result?
    var checking = false
    var pending: Bool?
    let now: Date
    let onToggle: (Bool) -> Void
    let onFix: (MacPermission) -> Void

    private var stream: SourceStream { resolved.stream }
    private var control: SourceStreamRow.Control { SourceStreamRow.control(resolved, pending: pending) }

    var body: some View {
        let trailing = SourceStreamRow.trailing(resolved, result: result, checking: checking, now: now)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    Text(stream.label)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(stream.state == .unavailable ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Text(quietLine)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(resolved.word == .needsAccess ? CicadaTheme.warning : CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                trailingView(trailing)
                switch control {
                case .toggle(let on):
                    Toggle(isOn: Binding(get: { on }, set: onToggle)) { EmptyView() }
                        .toggleStyle(.switch)
                        .controlSize(.mini)
                        .labelsHidden()
                        .accessibilityLabel(stream.label)
                case .setup:
                    EmptyView()
                }
            }
            if let fix = resolved.fix, resolved.word == .needsAccess {
                NeutralButton(title: fix == .accessibility ? Copy.SaveWhy.openAccessibility : Copy.Streams.openSetting,
                              size: .compact) { onFix(fix) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, CicadaTheme.scaled(14))
        .padding(.vertical, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
        .help(SourceStreamRow.help(stream) ?? quietLine)
        .accessibilityElement(children: .contain)
    }

    /// The line says why when the stream is waiting on a permission (the one hint, never a prompt), else how it is read.
    private var quietLine: String {
        if resolved.word == .needsAccess, let why = stream.why, !why.isEmpty { return why }
        return SourceStreamRow.line(stream)
    }

    @ViewBuilder
    private func trailingView(_ trailing: SourceStreamRow.Trailing) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if checking {
                Text(Copy.Streams.checking).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let text = trailing.text, !text.isEmpty {
                Text(text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            if let note = trailing.note {
                Text(note).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
            if let word = trailing.word {
                StatusWord(word: word.text, tone: word.tone(how: stream.how))
                    .help(trailing.help ?? "")
            } else if control == .setup, resolved.word == .off {
                // No switch to say it: a stream that needs the source's own setup says it is not on yet.
                StatusWord(word: Copy.Streams.off, tone: .off)
            }
        }
        .fixedSize()
    }
}
