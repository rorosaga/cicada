import SwiftUI

/// GitHub-style 53×7 activity grid. Cells are `CalendarCell`s; the colour is
/// the backend's quantile `level` through `CicadaTheme.heatRamp`.
struct HeatmapView: View {
    let days: [CalendarDay]
    @Binding var selected: CalendarDay?
    private let cellSize: CGFloat = 11
    private let gap: CGFloat = 3

    private var columns: [[CalendarCell?]] { CalendarLayout.columns(days.map(\.cell)) }
    private var byDate: [String: CalendarDay] { Dictionary(uniqueKeysWithValues: days.map { ($0.date, $0) }) }

    var body: some View {
        let cols = columns
        VStack(alignment: .leading, spacing: gap) {
            monthRow(cols)
            HStack(alignment: .top, spacing: gap) {
                weekdayColumn
                ForEach(Array(cols.enumerated()), id: \.offset) { _, col in
                    VStack(spacing: gap) {
                        ForEach(0..<7, id: \.self) { row in
                            cell(col[row])
                        }
                    }
                }
            }
            legend
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }

    private func cell(_ c: CalendarCell?) -> some View {
        RoundedRectangle(cornerRadius: 2)
            .fill(c.map { CicadaTheme.heatRamp(level: $0.level) } ?? Color.clear)
            .frame(width: cellSize, height: cellSize)
            .overlay {
                if let c, selected?.date == c.date {
                    RoundedRectangle(cornerRadius: 2).stroke(CicadaTheme.textPrimary, lineWidth: 1)
                }
            }
            .help(c.map(Self.tooltip) ?? "")
            .onTapGesture { if let c { selected = selected?.date == c.date ? nil : byDate[c.date] } }
    }

    /// The cell's hover text. Writes always, events only when there are any,
    /// tokens NEVER — the 2026-09-03 ruling on the G124 row took token counts
    /// out of the app; `CalendarCell.tokens` stays decoded but unrendered.
    /// Static and pure so the "never tokens" rule is unit-tested.
    static func tooltip(_ c: CalendarCell) -> String {
        var text = "\(c.date) · \(c.memoryWrites) memory write\(c.memoryWrites == 1 ? "" : "s")"
        if c.events > 0 { text += " · \(c.events) event\(c.events == 1 ? "" : "s")" }
        return text
    }

    private func monthRow(_ cols: [[CalendarCell?]]) -> some View {
        let labels = CalendarLayout.monthLabels(cols)
        return HStack(spacing: 0) {
            Spacer().frame(width: 28 + gap)
            ZStack(alignment: .leading) {
                ForEach(Array(labels.enumerated()), id: \.offset) { _, l in
                    Text(l.label).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        .offset(x: CGFloat(l.column) * (cellSize + gap))
                }
            }
            .frame(height: 14, alignment: .leading)
        }
    }

    /// Mon / Wed / Fri labelled, the rest blank — but every row still needs a
    /// DISTINCT id or `ForEach` folds the three blank rows into one and the
    /// column renders 5 rows against a 7-row grid.
    static let weekdayLabels = ["Mon", "", "Wed", "", "Fri", "", ""]

    private var weekdayColumn: some View {
        VStack(spacing: gap) {
            ForEach(Array(Self.weekdayLabels.enumerated()), id: \.offset) { _, day in
                Text(day)
                    .font(CicadaTheme.font(size: 9))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: 28, height: cellSize, alignment: .leading)
            }
        }
        .accessibilityHidden(true)
    }

    private var legend: some View {
        HStack(spacing: gap) {
            Spacer()
            Text("Less").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            ForEach(0..<5, id: \.self) { l in
                RoundedRectangle(cornerRadius: 2).fill(CicadaTheme.heatRamp(level: l)).frame(width: cellSize, height: cellSize)
            }
            Text("More").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
