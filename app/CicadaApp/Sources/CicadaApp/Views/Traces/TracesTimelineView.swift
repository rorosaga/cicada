import AppKit
import SwiftUI

// G218 — the traces browser: a day, its spans (time range, app, title, site) and a search; screenshots stay hidden
// until Touch ID or the login password (`TraceAuthenticator`). Pixels and screenshot text are fetched only after a
// successful unlock, held in memory only — never written to disk, never cached — and dropped when the sheet closes or
// five minutes after the unlock (`CicadaTiming.traceScreenshotsShown`). A search hit from a screenshot's text shows
// its words only once unlocked, for the same reason.
//
// DR-46 (the search field), DR-50 (empty states in words), DR-32 (every state said in words), DR-34 (row heights),
// DR-58 (day words from `RelativeDay`), DR-76 (the app's own field).

/// The browser's state, with no view in it. Every read goes through `TraceBackend`, so tests fake it.
@MainActor
@Observable
final class TracesBrowserModel {
    private(set) var days: [ISODay] = []
    private(set) var day: ISODay
    private(set) var timeline: TraceTimeline?
    private(set) var loading = false
    private(set) var problem: String?
    var query = ""
    private(set) var hits: [TraceSearchHit]?
    /// Screenshots may be shown (Touch ID passed, not yet hidden again).
    private(set) var unlocked = false
    private(set) var authFailed = false
    /// Pixels and text, in memory only.
    private(set) var images: [String: Data] = [:]
    private(set) var texts: [String: String] = [:]
    var selectedFrame: String?

    @ObservationIgnored private let backend: any TraceBackend
    @ObservationIgnored private let authenticator: any TraceAuthenticator
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let calendar: Calendar
    @ObservationIgnored private let hideAfter: TimeInterval
    @ObservationIgnored private var hideTask: Task<Void, Never>?

    init(backend: any TraceBackend, authenticator: any TraceAuthenticator, now: @escaping () -> Date = Date.init,
         calendar: Calendar = .autoupdatingCurrent, hideAfter: TimeInterval = CicadaTiming.traceScreenshotsShown) {
        self.backend = backend
        self.authenticator = authenticator
        self.now = now
        self.calendar = calendar
        self.hideAfter = hideAfter
        day = ISODay.today(now: now(), calendar: calendar)
    }

    var today: ISODay { ISODay.today(now: now(), calendar: calendar) }

    /// The days the store can hold: its oldest kept day through today, newest first, never more than it keeps.
    static func days(oldest: String?, keep: Int, today: ISODay) -> [ISODay] {
        let floor = today.adding(-(max(1, keep) - 1))
        let first = max(ISODay(oldest) ?? today, floor)
        guard first <= today else { return [today] }
        return (0...(today - first)).map { today.adding(-$0) }
    }

    func setStatus(_ status: TraceStoreStatus) {
        days = Self.days(oldest: status.oldestDay, keep: status.timelineDays, today: today)
        if !days.contains(day) { day = days.first ?? today }
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            timeline = try await backend.traceTimeline(day: day.description)
            problem = nil
        } catch {
            timeline = nil
            problem = TraceRecorder.describe(error)
        }
    }

    func select(_ next: ISODay) async {
        guard next != day else { return }
        day = next
        selectedFrame = nil
        await load()
    }

    func search() async {
        let words = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty else { hits = nil; return }
        do {
            hits = try await backend.traceSearch(words)
            problem = nil
        } catch {
            hits = []
            problem = TraceRecorder.describe(error)
        }
    }

    /// "Show screenshots": Touch ID or the login password first; nothing is fetched unless it passes.
    func unlock(reason: String = Copy.Traces.authReason) async {
        guard !unlocked else { return }
        let ok = await authenticator.authenticate(reason: reason)
        authFailed = !ok
        guard ok else { return }
        unlocked = true
        hideTask?.cancel()
        let seconds = hideAfter
        hideTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled else { return }
            self?.hide()
        }
    }

    /// One screenshot's pixels, once unlocked. Never before; never twice.
    func image(for id: String) async {
        guard unlocked, images[id] == nil else { return }
        guard let data = try? await backend.traceFrameImage(id: id), unlocked else { return }
        images[id] = data
    }

    /// One screenshot's text, once unlocked.
    func text(for id: String) async {
        guard unlocked, texts[id] == nil else { return }
        guard let answer = try? await backend.traceFrameText(id: id), unlocked else { return }
        texts[id] = answer.text
    }

    /// Hides the screenshots again and drops them from memory (the five minutes passed, or the person hid them).
    func hide() {
        hideTask?.cancel()
        hideTask = nil
        unlocked = false
        images = [:]
        texts = [:]
        selectedFrame = nil
    }

    /// The rail's second click (2026-10-19 "Say it once", (5)): back to the page's root — the newest day, no search, no
    /// screenshot open. The screenshots' unlock is left as it is: going home is not hiding them, and their own five
    /// minutes still run.
    func returnToRoot() async {
        query = ""
        hits = nil
        selectedFrame = nil
        await select(days.first ?? today)
    }

    /// The sheet closed: nothing of a screenshot stays.
    func close() {
        hide()
        authFailed = false
    }
}

struct TracesTimelineView: View {
    let status: TraceStoreStatus
    /// The sheet's Close. nil on the Traces page (owner 2026-10-26), which lays the days out as a column instead of a
    /// menu and has no close: leaving the page drops every screenshot the same way closing the sheet did.
    var onClose: (() -> Void)?
    /// Bumped by the Traces page when its rail cell is clicked again: the timeline returns to its root.
    var rootToken = 0

    @State private var model = TracesBrowserModel(backend: APIClient.shared, authenticator: LiveTraceAuthenticator())
    @FocusState private var searchFocused: Bool

    private var isPage: Bool { onClose == nil }

    var body: some View {
        Group {
            if isPage {
                HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                    dayColumn
                    content
                }
            } else {
                content
                    .padding(CicadaTheme.spacingXL)
                    .frame(width: CicadaTheme.scaled(720), height: CicadaTheme.scaled(560), alignment: .topLeading)
            }
        }
        .background(CicadaTheme.bgBase)
        .task(id: status.oldestDay) {
            model.setStatus(status)
            await model.load()
        }
        .onDisappear { model.close() }
        .onChange(of: rootToken) { _, _ in
            searchFocused = false
            Task { await model.returnToRoot() }
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            header
            if let problem = model.problem {
                Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    if model.hits != nil { hitsList } else { dayView }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    /// The page's days, newest first: one row each, the open one selected (DR-22's selection: `bgSelected`, never the
    /// accent). A switch is instant (DR-60).
    private var dayColumn: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.Traces.daysSection)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(model.days, id: \.self) { day in
                        let selected = day == model.day && model.hits == nil
                        Button {
                            Task { await model.select(day) }
                        } label: {
                            Text(dayLabel(day)).font(CicadaTheme.rowFont)
                                .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                                .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine),
                                       alignment: .leading)
                                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                                    .fill(selected ? CicadaTheme.bgSelected : Color.clear))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.cicadaPlain)
                        .help(RelativeDay.full(day))
                        .accessibilityAddTraits(selected ? [.isSelected] : [])
                    }
                }
            }
        }
        .frame(width: CicadaTheme.scaled(168), alignment: .topLeading)
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if isPage {
                Text(dayLabel(model.day)).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
            } else {
                Text(Copy.Traces.browserTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                dayMenu
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            TextField("", text: $model.query)
                .focused($searchFocused)
                .cicadaField(isFocused: searchFocused, prompt: Copy.Traces.searchPrompt, isEmpty: model.query.isEmpty)
                .frame(width: CicadaTheme.scaled(220))
                .onSubmit { Task { await model.search() } }
                .onChange(of: model.query) { _, words in
                    if words.isEmpty { Task { await model.search() } }
                }
            if let onClose {
                IconButton(systemName: "xmark", help: Copy.Traces.close, accessibilityLabel: Copy.Traces.close,
                           shortcut: .cancelAction) {
                    model.close()
                    onClose()
                }
            }
        }
    }

    private var dayMenu: some View {
        Menu {
            ForEach(model.days, id: \.self) { day in
                Button(dayLabel(day)) { Task { await model.select(day) } }
            }
        } label: {
            Text(dayLabel(model.day)).font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(RelativeDay.full(model.day))
    }

    private func dayLabel(_ day: ISODay) -> String { RelativeDay.phrase(day, today: model.today) }

    // MARK: - A day

    @ViewBuilder
    private var dayView: some View {
        if model.days.isEmpty && model.timeline == nil && !model.loading {
            emptyLine(Copy.Traces.noDays)
        } else if let timeline = model.timeline {
            if !timeline.frames.isEmpty { screenshots(timeline.frames) }
            if timeline.spans.isEmpty {
                emptyLine(Copy.Traces.nothingThisDay)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(timeline.spans) { span in spanRow(span) }
                }
            }
            if timeline.unreadable > 0 {
                Text(Copy.Traces.unreadable(timeline.unreadable)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        } else if model.loading {
            emptyLine(Copy.Traces.loading)
        }
    }

    private func spanRow(_ span: TraceStoredSpan) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            Text(timeRange(span.start, span.end)).font(CicadaTheme.metaFont).monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(128), alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(span.app).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                let detail = Eyebrow.text(span.title ?? "", span.host ?? "")
                if !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }

    // MARK: - Screenshots

    @ViewBuilder
    private func screenshots(_ frames: [TraceFrameMeta]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SectionLabel(Copy.Traces.screenshotCount(frames.count))
                Spacer()
                if model.unlocked {
                    TextButton(title: Copy.Traces.hideScreenshots) { model.hide() }
                } else {
                    NeutralButton(title: Copy.Traces.showScreenshots, systemImage: "touchid", size: .compact,
                                  help: Copy.Traces.showScreenshotsHelp) {
                        Task { await model.unlock() }
                    }
                }
            }
            if model.authFailed && !model.unlocked {
                Text(Copy.Traces.authFailed).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if model.unlocked {
                Text(Copy.Traces.screenshotsHiddenAgain).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                if let id = model.selectedFrame, let frame = frames.first(where: { $0.id == id }) {
                    selected(frame)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(150)),
                                             spacing: CicadaTheme.spacingSM)],
                          alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(frames) { frame in thumbnail(frame) }
                }
            }
        }
    }

    private func thumbnail(_ frame: TraceFrameMeta) -> some View {
        Button {
            model.selectedFrame = frame.id
            Task { await model.text(for: frame.id) }
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Group {
                    if let data = model.images[frame.id], let image = NSImage(data: data) {
                        Image(nsImage: image).resizable().aspectRatio(contentMode: .fit)
                    } else {
                        CicadaTheme.bgFocus
                    }
                }
                .frame(height: CicadaTheme.scaled(90))
                .frame(maxWidth: .infinity)
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .ringed(model.selectedFrame == frame.id ? .strong : .resting,
                        in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                Text(Eyebrow.text(time(frame.at), frame.app)).font(CicadaTheme.captionFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
        }
        .buttonStyle(.cicadaPlain)
        .task(id: model.unlocked) { await model.image(for: frame.id) }
    }

    private func selected(_ frame: TraceFrameMeta) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let data = model.images[frame.id], let image = NSImage(data: data) {
                Image(nsImage: image).resizable().aspectRatio(contentMode: .fit)
                    .frame(maxHeight: CicadaTheme.scaled(320))
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            }
            if frame.hasText, let text = model.texts[frame.id], !text.isEmpty {
                SectionLabel(Copy.Traces.readText)
                Text(text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .lineLimit(12)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: - Search

    @ViewBuilder
    private var hitsList: some View {
        if let hits = model.hits, hits.isEmpty {
            emptyLine(Copy.Traces.noHits)
        } else if let hits = model.hits {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(hits) { hit in hitRow(hit) }
            }
        }
    }

    private func hitRow(_ hit: TraceSearchHit) -> some View {
        let fromScreenshot = hit.kind == "frame"
        let range = hit.end.map { timeRange(hit.at, $0) } ?? time(hit.at)
        let day = ISODay(hit.at).map { RelativeDay.phrase($0, today: model.today) } ?? ""
        return HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            Text(Eyebrow.text(day, range)).font(CicadaTheme.metaFont).monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(170), alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(fromScreenshot ? Eyebrow.text(Copy.Traces.readText, hit.app ?? "") : (hit.app ?? ""))
                    .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                let detail = Eyebrow.text(hit.title ?? "", hit.url.flatMap { URL(string: $0)?.host } ?? "")
                if !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                // A screenshot's words are shown only once screenshots are.
                if let snippet = hit.snippet, !snippet.isEmpty, !fromScreenshot || model.unlocked {
                    Text(snippet).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }

    // MARK: - Pieces

    private func emptyLine(_ words: String) -> some View {
        Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.top, CicadaTheme.spacingXXL)
    }

    private func time(_ stamp: String) -> String {
        guard let date = TraceClock.parse(stamp) else { return "" }
        return date.formatted(date: .omitted, time: .shortened)
    }

    private func timeRange(_ start: String, _ end: String) -> String {
        let a = time(start)
        let b = time(end)
        return b.isEmpty || a == b ? a : "\(a) – \(b)"
    }
}
