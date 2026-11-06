import SwiftUI

/// ROR-126 — after an export is uploaded, before anything becomes an episode: a start date and a tick per chat.
/// One component for the intake preview and the Welcome's staged exports; it owns no state, every change goes through
/// `change`, so the host (the router's preview, or a Welcome drop) keeps the choice and sends it with the import.
///
/// DR-16 type steps, DR-40 text buttons, DR-5 no accent: the ticks are the system's own checkbox, the start date the
/// system's date field, and the list is the same quiet rows the title list always was.
struct ExportChoiceView: View {
    let preview: IntakePreview
    let change: ((inout IntakePreview) -> Void) -> Void

    @State private var filter = ""

    private var offered: [IntakeTitle] {
        preview.titles.filter { $0.key != nil && ($0.status == "new" || $0.status == "grown") }
    }

    private var shown: [IntakeTitle] {
        filter.isEmpty ? offered : offered.filter { $0.title.localizedCaseInsensitiveContains(filter) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.exportChoiceLead).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            startRow
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField(Copy.intakeFilterPlaceholder, text: $filter)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(Copy.intakeFilterLabel)
                TextButton(title: Copy.exportChoiceSelectAll) { set(shown, included: true) }
                TextButton(title: Copy.exportChoiceSelectNone) { set(shown, included: false) }
            }
            Text(Copy.exportChoiceCount(preview.chatImportCount, of: offered.count))
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary).monospacedDigit()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(shown.enumerated()), id: \.offset) { _, t in row(t) }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(200))
            Text(Copy.exportChoiceRemembered).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: Start date

    private static let day: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var startRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.exportChoiceStart).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            if let since = preview.since, let date = Self.day.date(from: since) {
                DatePicker(Copy.exportChoiceStart,
                           selection: Binding(get: { date },
                                              set: { new in change { $0.since = Self.day.string(from: new) } }),
                           in: bounds, displayedComponents: .date)
                    .labelsHidden()
                    .datePickerStyle(.field)
                TextButton(title: Copy.exportChoiceEverything) { change { $0.since = nil } }
            } else {
                Text(Copy.exportChoiceEverything).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                if preview.titleDays != nil {
                    TextButton(title: Copy.exportChoicePickDate) {
                        change { $0.since = preview.titleDays?.lowerBound }
                    }
                }
            }
            Spacer()
        }
    }

    private var bounds: ClosedRange<Date> {
        guard let days = preview.titleDays, let lo = Self.day.date(from: days.lowerBound),
              let hi = Self.day.date(from: days.upperBound) else { return Date.distantPast...Date() }
        return lo...hi
    }

    // MARK: Rows

    private func row(_ t: IntakeTitle) -> some View {
        let key = t.key ?? ""
        let included = preview.includes(t)
        let beforeStart = !(preview.deselected.contains(key)) && !included
        return HStack(spacing: CicadaTheme.spacingSM) {
            Toggle(isOn: Binding(get: { !preview.deselected.contains(key) },
                                 set: { on in change { if on { $0.deselected.remove(key) } else { $0.deselected.insert(key) } } })) {
                Text(t.title).font(CicadaTheme.bodyFont).lineLimit(1)
                    .foregroundStyle(included ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            }
            .toggleStyle(.checkbox)
            Spacer()
            if t.deselected {
                Text(Copy.exportChoiceLeftOutBefore).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let date = t.date {
                Text(date).font(CicadaTheme.captionFont)
                    .foregroundStyle(beforeStart ? CicadaTheme.textTertiary.opacity(0.6) : CicadaTheme.textTertiary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func set(_ rows: [IntakeTitle], included: Bool) {
        let keys = rows.compactMap(\.key)
        change { p in
            if included { p.deselected.subtract(keys) } else { p.deselected.formUnion(keys) }
        }
    }
}
