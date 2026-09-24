import SwiftUI

/// Round 4 (T-Sources) — the row every syncing source wears: bare mark, name and what it reads, what came in, and on
/// the right what it is doing — "Syncing now" with an × (R-SR11), or "Last synced 2 minutes ago" (R-SR12). The row
/// renders and decides nothing: `SourceRowModel` is built by pure functions each host calls, and `accessory` is the
/// host's own action (Turn on, Sync now, a switch). One component, many hosts (the `FoundRow` precedent).
struct SourceRow<Accessory: View>: View {
    static var markSize: CGFloat { 24 }

    let model: SourceRowModel
    /// The host's `TimelineView` date, so "2 minutes ago" moves without a network call (DR-58).
    var now: Date = Date()
    /// Present only where a stop means something; the × shows only while the run says it can be stopped.
    var onCancel: (() -> Void)? = nil
    @ViewBuilder var accessory: () -> Accessory

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            OriginMark(origin: model.origin, size: CicadaTheme.scaled(Self.markSize))
                .markHover(hovering: hovering)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(model.title)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let meta = model.meta {
                        Text(meta)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                if let line = SourceRowText.secondLine(model) {
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .help(line)
                }
                if case .syncing(_, let fraction?, _) = model.status { SyncMeter(fraction: fraction) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            trailing
            accessory()
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
        .padding(.horizontal, CicadaTheme.scaled(10))
        .background(hovering ? CicadaTheme.bgHover : Color.clear,
                    in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onHover { hovering = $0 }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(SourceRowText.accessibilityLabel(model, now: now))
    }

    @ViewBuilder
    private var trailing: some View {
        switch model.status {
        case .idle:
            EmptyView()
        case .syncing(_, _, let cancellable):
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                Text(Copy.syncingNow).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                if cancellable, let onCancel {
                    IconButton(systemName: "xmark", help: Copy.stopSyncingHelp,
                               accessibilityLabel: "\(Copy.stopSyncing), \(model.title)", action: onCancel)
                }
            }
        case .synced:
            HStack(spacing: CicadaTheme.scaled(6)) {
                Circle().fill(CicadaTheme.success)
                    .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                trailingText(CicadaTheme.textTertiary)
            }
        case .problem:
            trailingText(CicadaTheme.warning)
        case .notYet, .imported:
            trailingText(CicadaTheme.textTertiary)
        }
    }

    private func trailingText(_ color: Color) -> some View {
        let text = SourceRowText.trailing(model.status, now: now) ?? ""
        return Text(text).font(CicadaTheme.metaFont).foregroundStyle(color).lineLimit(1).help(text)
    }
}

extension SourceRow where Accessory == EmptyView {
    init(model: SourceRowModel, now: Date = Date(), onCancel: (() -> Void)? = nil) {
        self.init(model: model, now: now, onCancel: onCancel) { EmptyView() }
    }
}

/// A thin neutral meter for a run that knows its fraction — never the accent (DR-5), never animated (a value, DR-66).
struct SyncMeter: View {
    let fraction: Double

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(CicadaTheme.bgSelected)
                Capsule().fill(CicadaTheme.textSecondary)
                    .frame(width: geo.size.width * min(max(fraction, 0), 1))
            }
        }
        .frame(width: CicadaTheme.scaled(96), height: CicadaTheme.scaled(3))
        .accessibilityHidden(true)
    }
}
