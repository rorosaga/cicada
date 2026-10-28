import AppKit
import SwiftUI

// G218 — the Traces page. Owner 2026-10-26: "its own page, so we can actually see the trace of the screenshots". Owner
// 2026-10-28 (the traces redesign, mock 11): consolidation is its own feature, and traces are managed by day.
//
//   Into memory          — "Learn from my day" (one switch, off) and "What you watch and read" (any site, on).
//   …as Sleep would read it — the exact counted digest, computed on this Mac with no model, before the switch is on.
//   What traces added    — a count, Show, and "Remove from memory…" (one commit) with Undo.
//   Days                 — one card per day with the screenshot that stands for it ("kind of like BeReal"), behind
//                          Touch ID like every screenshot; open a day to see exactly what was captured and delete any
//                          item or the whole day; "N screens connected" when more than one was.
//
// No drop-downs on the page (owner): an empty section is hidden and a long list is capped with "All N". Every G218
// rail holds: the screenshots stay behind Touch ID or the login password and are fetched only after it, held in memory
// and dropped when the page goes or five minutes pass (`TracesBrowserModel`); every read is This Mac's backend, never the
// network or a remote door; nothing here is a mention.
//
// DR-4 (native switches follow the system accent), DR-7 (no semantic colour; the bars are neutral ink, data not
// decoration), DR-22 (the rail cell), DR-25 (the eyebrow row's trailing actions), DR-40 (neutral buttons; Wipe, Delete
// day and Remove from memory behind a confirmation in words), DR-50 (empty states in words), DR-58 (day words from
// `RelativeDay`), DR-60 (instant switches). Depth is a ring (`ringed`), never a shadow.

/// What the page knows about memory: the preview and what traces added. Every read goes through `TraceBackend`.
@MainActor
@Observable
final class TracesMemoryModel {
    private(set) var preview: TraceDigestPreview?
    private(set) var added: TraceAdded?
    /// The last thing said after a removal or an undo.
    private(set) var note: String?
    private(set) var busy = false

    @ObservationIgnored private let backend: any TraceBackend

    init(backend: any TraceBackend) { self.backend = backend }

    func load() async {
        preview = try? await backend.tracePreview(day: nil)
        added = try? await backend.traceAdded()
    }

    /// The newest removal that can still be undone.
    var undoable: TraceAdded.Removal? { added?.removals.last }

    var hasAdded: Bool { (added?.beliefs ?? 0) + (added?.progress ?? 0) > 0 }

    func removeFromMemory() async {
        busy = true
        defer { busy = false }
        do {
            let result = try await backend.traceRemoveFromMemory()
            note = result.removed > 0 ? Copy.Traces.removed(result.removed) : Copy.Traces.nothingToRemove
        } catch {
            note = TraceRecorder.describe(error)
        }
        added = try? await backend.traceAdded()
    }

    func undo() async {
        guard let removal = undoable else { return }
        busy = true
        defer { busy = false }
        do {
            note = Copy.Traces.restored(try await backend.traceUndoRemoval(id: removal.id))
        } catch {
            note = TraceRecorder.describe(error)
        }
        added = try? await backend.traceAdded()
    }
}

/// The page's pure parts, with no view in them.
enum TracesPageLogic {
    struct DigestRow: Equatable, Identifiable {
        var id: String
        var label: String
        var title: String
        var detail: String
        var seconds: Int
        var projectId: String?
    }

    /// The digest's rows in the mock's order; a part under a minute is not shown (an empty section is hidden).
    static func rows(_ counts: TraceDigestPreview.Counts) -> [DigestRow] {
        var out: [DigestRow] = []
        for (i, p) in counts.projects.enumerated() where p.seconds >= 60 {
            out.append(DigestRow(id: "project-\(p.id)", label: i == 0 ? Copy.Traces.yourProjects : "", title: p.name,
                                 detail: p.apps.joined(separator: ", "), seconds: p.seconds, projectId: p.id))
        }
        let r = counts.reading
        if r.seconds >= 60 {
            let what = [r.pages > 0 ? Copy.Traces.pagesOnSites(r.pages, r.siteCount) : "", r.apps.joined(separator: ", ")]
                .filter { !$0.isEmpty }.joined(separator: " · ")
            out.append(DigestRow(id: "reading", label: Copy.Traces.reading, title: what,
                                 detail: r.sites.prefix(3).joined(separator: ", "), seconds: r.seconds))
        }
        let w = counts.watching
        if w.seconds >= 60 {
            out.append(DigestRow(id: "watching", label: Copy.Traces.watching, title: Copy.Traces.videos(w.videos),
                                 detail: w.platforms.joined(separator: ", "), seconds: w.seconds))
        }
        let c = counts.calls
        if c.seconds >= 60 {
            out.append(DigestRow(id: "calls", label: Copy.Traces.calls, title: Copy.Traces.callCount(c.count),
                                 detail: c.apps.joined(separator: ", "), seconds: c.seconds))
        }
        let e = counts.rest
        if e.seconds >= 60 {
            let switches = e.busiestSwitches > 0 ? Copy.Traces.switchesAtBusiest(e.busiestSwitches) : ""
            out.append(DigestRow(id: "else", label: Copy.Traces.everythingElse,
                                 title: e.apps.prefix(4).joined(separator: ", "), detail: switches, seconds: e.seconds))
        }
        return out
    }

    /// A long list capped: what shows, and how many wait behind "All N" (0 when nothing does).
    static func capped<T>(_ list: [T], limit: Int, expanded: Bool) -> (shown: [T], more: Int) {
        guard !expanded, list.count > limit else { return (list, 0) }
        return (Array(list.prefix(limit)), list.count)
    }

    /// Time per app or per site over a day's spans, the most first.
    static func totals(_ spans: [TraceStoredSpan], by key: (TraceStoredSpan) -> String?) -> [(name: String, seconds: Int)] {
        var sums: [String: Double] = [:]
        for span in spans {
            guard let name = key(span), !name.isEmpty, let a = TraceClock.parse(span.start),
                  let b = TraceClock.parse(span.end), b > a else { continue }
            sums[name, default: 0] += b.timeIntervalSince(a)
        }
        return sums.map { (name: $0.key, seconds: Int($0.value)) }
            .sorted { $0.seconds != $1.seconds ? $0.seconds > $1.seconds : $0.name < $1.name }
    }

    /// A day's screenshots as moments: frames taken at one instant (one per screen) stay together, main screen first.
    static func moments(_ frames: [TraceFrameMeta]) -> [[TraceFrameMeta]] {
        var order: [String] = []
        var groups: [String: [TraceFrameMeta]] = [:]
        for f in frames {
            if groups[f.at] == nil { order.append(f.at) }
            groups[f.at, default: []].append(f)
        }
        return order.map { at in groups[at, default: []].sorted { ($0.display ?? 0) < ($1.display ?? 0) } }
    }
}

struct TracesPage: View {
    @Environment(TraceRecorder.self) private var recorder: TraceRecorder?
    @State private var showSettings = false
    @State private var showConsent = false
    @State private var confirmWipe = false
    @State private var confirmRemove = false
    @State private var showAdded = false
    @State private var allAdded = false
    @State private var note: String?
    @State private var memory = TracesMemoryModel(backend: APIClient.shared)
    /// The rail's second click returns the page to its root through the shared mechanism (`onRailReselect` →
    /// `popToRoot`: instant from ⌘, eased from a click — DR-60/61): sheets and questions close, the note goes, and the
    /// days go back to their cards with no search (`TracesBrowserModel.returnToRoot`).
    @State private var rootToken = 0
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    NeutralButton(title: Copy.Traces.settings, systemImage: "slider.horizontal.3", size: .compact,
                                  help: Copy.Traces.settingsHelp) { showSettings = true }
                    NeutralButton(title: Copy.Traces.wipe, size: .compact, isDisabled: recorder == nil) {
                        confirmWipe = true
                    }
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        caption(Copy.Traces.staysHere(shotDays: recorder?.settings.shotDays ?? 7,
                                                      timelineDays: recorder?.settings.timelineDays ?? 30))
                        if let note { caption(note) }
                    }
                    if let recorder, recorder.state == .recording || recorder.state == .paused {
                        intoMemory(recorder)
                    }
                    previewSection
                    addedSection
                    if let recorder {
                        TracesDaysView(status: recorder.status, rootToken: rootToken)
                    }
                }
                .frame(maxWidth: CicadaTheme.scaled(860), alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.bottom, CicadaTheme.spacingXL)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .task {
            await recorder?.refreshStatus()
            await memory.load()
        }
        .onRailReselect(.traces, router: router) {
            router?.popToRoot(reduceMotion: reduceMotion) {
                showSettings = false
                showConsent = false
                confirmWipe = false
                confirmRemove = false
                showAdded = false
                note = nil
                rootToken &+= 1
            }
        }
        .sheet(isPresented: $showSettings) {
            TracesSettingsSheet { showSettings = false }
        }
        .sheet(isPresented: $showConsent) {
            TracesConsentSheet { showConsent = false }
        }
        .confirmationDialog(Copy.Traces.wipeTitle, isPresented: $confirmWipe) {
            Button(Copy.Traces.wipeConfirm, role: .destructive) { wipe() }
            Button(Copy.Traces.cancel, role: .cancel) {}
        } message: {
            Text(Copy.Traces.wipeMessage)
        }
        .confirmationDialog(Copy.Traces.removeTitle, isPresented: $confirmRemove) {
            Button(Copy.Traces.removeConfirm, role: .destructive) { Task { await memory.removeFromMemory() } }
            Button(Copy.Traces.cancel, role: .cancel) {}
        } message: {
            Text(Copy.Traces.removeMessage)
        }
    }

    private var eyebrow: String {
        guard let recorder else { return Copy.Traces.title }
        return Eyebrow.text(Copy.Traces.title,
                            TracesControlsLogic.stateLine(recorder.state, settings: recorder.settings, now: .now))
    }

    // MARK: - Into memory

    private func intoMemory(_ recorder: TraceRecorder) -> some View {
        section(Copy.Traces.memorySection) {
            card {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    toggle(Copy.Traces.learn, help: Copy.Traces.learnHelp, isOn: recorder.settings.learnFromDay) { on in
                        patch(recorder, ["learn_from_day": .bool(on)])
                    }
                    toggle(Copy.Traces.watchAndRead, help: Copy.Traces.watchAndReadHelp,
                           isOn: recorder.settings.watchAndRead) { on in
                        patch(recorder, ["watch_and_read": .bool(on)])
                    }
                    if recorder.settings.readingNotice {
                        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                            caption(Copy.Traces.readingNotice)
                            Spacer(minLength: CicadaTheme.spacingSM)
                            TextButton(title: Copy.Traces.gotIt, inline: true) {
                                patch(recorder, ["reading_notice": .bool(false)])
                            }
                        }
                    }
                    if recorder.offersAllScreens {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            caption(Copy.Traces.allScreensOffer)
                            Spacer(minLength: CicadaTheme.spacingSM)
                            NeutralButton(title: Copy.Traces.review, size: .compact) { showConsent = true }
                        }
                    }
                }
            }
        }
    }

    // MARK: - The preview

    @ViewBuilder
    private var previewSection: some View {
        if let preview = memory.preview, let counts = preview.counts {
            let rows = TracesPageLogic.rows(counts)
            if !rows.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack {
                        SectionLabel(previewTitle(preview.day))
                        Spacer()
                        Text(Copy.Traces.previewTrailing).font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    card {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            let longest = max(1, rows.map(\.seconds).max() ?? 1)
                            ForEach(rows) { row in digestRow(row, longest: longest) }
                            caption(Copy.Traces.previewFoot).padding(.top, CicadaTheme.spacingXS)
                        }
                    }
                }
            }
        }
    }

    private func previewTitle(_ day: String) -> String {
        guard let d = ISODay(day) else { return Copy.Traces.previewSection }
        let today = ISODay.today(now: .now, calendar: .autoupdatingCurrent)
        return d == today.adding(-1) ? Copy.Traces.previewSection
            : Copy.Traces.previewSectionFor(RelativeDay.phrase(d, today: today))
    }

    private func digestRow(_ row: TracesPageLogic.DigestRow, longest: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            Text(row.label).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(130), alignment: .leading)
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                // Neutral ink, one hue: data, not decoration (DR-7).
                Capsule().fill(row.projectId != nil ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(max(6, 140 * CGFloat(row.seconds) / CGFloat(longest))),
                           height: CicadaTheme.scaled(5))
                    .accessibilityHidden(true)
                Text(row.title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                if !row.detail.isEmpty {
                    Text("· " + row.detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Text(Copy.Traces.duration(row.seconds)).font(CicadaTheme.bodyFont).monospacedDigit()
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - What traces added

    @ViewBuilder
    private var addedSection: some View {
        if let added = memory.added, memory.hasAdded || memory.undoable != nil || memory.note != nil {
            section(Copy.Traces.addedSection) {
                card {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        if memory.hasAdded {
                            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(Copy.Traces.added(beliefs: added.beliefs, progress: added.progress,
                                                           since: added.since.flatMap(ISODay.init).map(dayWords)))
                                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                                    caption(Copy.Traces.addedLine)
                                }
                                Spacer(minLength: CicadaTheme.spacingSM)
                                TextButton(title: showAdded ? Copy.Traces.hide : Copy.Traces.show) { showAdded.toggle() }
                                NeutralButton(title: Copy.Traces.removeFromMemory, size: .compact,
                                              isDisabled: memory.busy) { confirmRemove = true }
                            }
                            if showAdded { addedList(added.items) }
                        }
                        if memory.note != nil || memory.undoable != nil {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                if let note = memory.note { caption(note) }
                                if memory.undoable != nil {
                                    TextButton(title: Copy.Traces.undo, inline: true) { Task { await memory.undo() } }
                                        .disabled(memory.busy)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func addedList(_ items: [TraceAdded.Item]) -> some View {
        let capped = TracesPageLogic.capped(items, limit: 5, expanded: allAdded)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(capped.shown) { item in
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(item.text).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let day = item.day.flatMap(ISODay.init) {
                        Text(dayWords(day)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            if capped.more > 0 {
                TextButton(title: Copy.Traces.allCount(capped.more), inline: true, flushLeading: true) { allAdded = true }
            }
        }
    }

    private func dayWords(_ day: ISODay) -> String {
        RelativeDay.phrase(day, today: ISODay.today(now: .now, calendar: .autoupdatingCurrent))
    }

    // MARK: - Pieces

    private func caption(_ words: String) -> some View {
        Text(words).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            content()
        }
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content()
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }

    private func toggle(_ title: String, help: String, isOn: Bool, set: @escaping (Bool) -> Void) -> some View {
        Toggle(isOn: Binding(get: { isOn }, set: set)) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                caption(help)
            }
        }
        .toggleStyle(.switch)
        .controlSize(.small)
    }

    private func patch(_ recorder: TraceRecorder, _ values: [String: TracePatchValue]) {
        Task { @MainActor in
            do {
                try await recorder.update(values)
                note = nil
                await memory.load()
            } catch {
                note = TraceRecorder.describe(error)
            }
        }
    }

    private func wipe() {
        guard let recorder else { return }
        Task { @MainActor in
            do { try await recorder.wipe(); note = Copy.Traces.wiped } catch { note = TraceRecorder.describe(error) }
        }
    }
}

/// The page's days (owner 2026-10-28): one card per day with the screenshot that stands for it — behind Touch ID like
/// every screenshot — then, opened, exactly what that day holds, every item deletable.
struct TracesDaysView: View {
    let status: TraceStoreStatus
    var rootToken = 0

    @State private var model = TracesBrowserModel(backend: APIClient.shared, authenticator: LiveTraceAuthenticator())
    @State private var expanded: Set<String> = []
    @State private var confirmDeleteDay = false
    @FocusState private var searchFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            header
            if let problem = model.problem {
                Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if model.hits != nil {
                TracesHitsList(model: model)
            } else if let day = model.openDay {
                dayDetail(day)
            } else {
                cards
            }
        }
        .task(id: status.oldestDay) {
            model.setStatus(status)
            await model.loadCards()
        }
        .onDisappear { model.close() }
        .onChange(of: rootToken) { _, _ in
            searchFocused = false
            expanded = []
            Task { await model.returnToRoot() }
        }
        .confirmationDialog(Copy.Traces.deleteDayTitle(dayLabel(model.openDay ?? model.today)),
                            isPresented: $confirmDeleteDay) {
            Button(Copy.Traces.deleteDayConfirm, role: .destructive) { Task { await model.deleteDay() } }
            Button(Copy.Traces.cancel, role: .cancel) {}
        } message: {
            Text(Copy.Traces.deleteDayMessage)
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let day = model.openDay, model.hits == nil {
                TextButton(title: Copy.Traces.allDays, help: Copy.Traces.allDaysHelp, flushLeading: true) {
                    expanded = []
                    Task { await model.backToDays() }
                }
                Text(dayLabel(day)).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                if let screens = model.timeline?.screens, screens > 1 {
                    Text(Copy.Traces.screensConnected(screens)).font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else {
                SectionLabel(Copy.Traces.daysSection)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            screenshotsButton
            if model.openDay != nil && model.hits == nil {
                NeutralButton(title: Copy.Traces.deleteDay, size: .compact) { confirmDeleteDay = true }
            }
            TextField("", text: $model.query)
                .focused($searchFocused)
                .cicadaField(isFocused: searchFocused, prompt: Copy.Traces.searchPrompt, isEmpty: model.query.isEmpty)
                .frame(width: CicadaTheme.scaled(220))
                .onSubmit { Task { await model.search() } }
                .onChange(of: model.query) { _, words in
                    if words.isEmpty { Task { await model.search() } }
                }
        }
    }

    @ViewBuilder
    private var screenshotsButton: some View {
        if model.unlocked {
            TextButton(title: Copy.Traces.hideScreenshots) { model.hide() }
        } else if model.cards.contains(where: { $0.frames > 0 }) || !(model.timeline?.frames.isEmpty ?? true) {
            NeutralButton(title: Copy.Traces.showScreenshots, systemImage: "touchid", size: .compact,
                          help: Copy.Traces.showScreenshotsHelp) {
                Task { await model.unlock() }
            }
        }
    }

    // MARK: - The cards

    @ViewBuilder
    private var cards: some View {
        if model.cards.isEmpty {
            Text(Copy.Traces.noDays).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                .padding(.vertical, CicadaTheme.spacingLG)
        } else {
            if model.authFailed && !model.unlocked {
                Text(Copy.Traces.authFailed).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(156), maximum: CicadaTheme.scaled(220)),
                                         spacing: CicadaTheme.spacingMD)],
                      alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(model.cards) { card in dayCard(card) }
            }
        }
    }

    private func dayCard(_ card: TraceDayCard) -> some View {
        Button {
            Task { await model.open(ISODay(card.day) ?? model.today) }
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ZStack {
                    CicadaTheme.bgFocus
                    if let cover = card.cover, let data = model.images[cover], let image = NSImage(data: data) {
                        Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                    } else if card.cover != nil {
                        Image(systemName: "lock").font(CicadaTheme.icon(.inline))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .help(Copy.Traces.lockedCover)
                    }
                }
                .frame(height: CicadaTheme.scaled(104))
                .frame(maxWidth: .infinity)
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(dayLabel(ISODay(card.day) ?? model.today)).font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if card.screens > 1 {
                        Image(systemName: "rectangle.on.rectangle").font(CicadaTheme.icon(.inline))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .help(Copy.Traces.screensConnected(card.screens))
                            .accessibilityLabel(Copy.Traces.screensConnected(card.screens))
                    }
                }
                Text(Copy.Traces.dayLine(seconds: card.seconds, apps: card.apps)).font(CicadaTheme.captionFont)
                    .monospacedDigit().foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(RelativeDay.full(ISODay(card.day) ?? model.today))
        .task(id: model.unlocked) { if let cover = card.cover { await model.image(for: cover) } }
    }

    // MARK: - One day

    @ViewBuilder
    private func dayDetail(_ day: ISODay) -> some View {
        if let timeline = model.timeline, timeline.day == day.description {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                if !timeline.frames.isEmpty { screenshots(timeline.frames, screens: timeline.screens ?? 1) }
                let apps = TracesPageLogic.totals(timeline.spans) { $0.app }
                if !apps.isEmpty { totalsSection(Copy.Traces.appsSection, key: "apps", rows: apps) }
                let sites = TracesPageLogic.totals(timeline.spans) { $0.host }
                if !sites.isEmpty { totalsSection(Copy.Traces.sitesSection, key: "sites", rows: sites) }
                if timeline.spans.isEmpty && timeline.frames.isEmpty {
                    Text(Copy.Traces.nothingThisDay).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                } else if !timeline.spans.isEmpty {
                    spansSection(timeline.spans)
                }
                if timeline.unreadable > 0 {
                    Text(Copy.Traces.unreadable(timeline.unreadable)).font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        } else if model.loading {
            Text(Copy.Traces.loading).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func screenshots(_ frames: [TraceFrameMeta], screens: Int) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Traces.screenshotCount(frames.count))
            if model.authFailed && !model.unlocked {
                Text(Copy.Traces.authFailed).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if model.unlocked {
                Text(Copy.Traces.screenshotsHiddenAgain).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                if let id = model.selectedFrame, let frame = frames.first(where: { $0.id == id }) {
                    selected(frame)
                }
                let moments = TracesPageLogic.moments(frames)
                let capped = TracesPageLogic.capped(moments, limit: 24, expanded: expanded.contains("shots"))
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(150)),
                                             spacing: CicadaTheme.spacingSM)],
                          alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(capped.shown.flatMap { $0 }) { frame in thumbnail(frame) }
                }
                if capped.more > 0 { allLink(capped.more, key: "shots") }
            }
        }
    }

    private func thumbnail(_ frame: TraceFrameMeta) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Button {
                model.selectedFrame = frame.id
                Task { await model.text(for: frame.id) }
            } label: {
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
            }
            .buttonStyle(.cicadaPlain)
            HStack(spacing: CicadaTheme.spacingXS) {
                let screen = (frame.displays ?? 0) > 1 ? Copy.Traces.screenOf(frame.display ?? 1, frame.displays ?? 1) : ""
                Text(Eyebrow.text(time(frame.at), frame.app, screen)).font(CicadaTheme.captionFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                Spacer(minLength: 0)
                IconButton(systemName: "trash", help: Copy.Traces.deleteHelp(Copy.Traces.screenshotSection.lowercased()),
                           accessibilityLabel: Copy.Traces.deleteItem) {
                    Task { await model.delete(frames: [frame.id]) }
                }
            }
        }
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
                    .textSelection(.enabled).lineLimit(12).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func totalsSection(_ title: String, key: String, rows: [(name: String, seconds: Int)]) -> some View {
        let capped = TracesPageLogic.capped(rows, limit: 8, expanded: expanded.contains(key))
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(title)
            ForEach(capped.shown, id: \.name) { row in
                HStack {
                    Text(row.name).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    Text(Copy.Traces.duration(row.seconds)).font(CicadaTheme.metaFont).monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            }
            if capped.more > 0 { allLink(capped.more, key: key) }
        }
    }

    private func spansSection(_ spans: [TraceStoredSpan]) -> some View {
        let capped = TracesPageLogic.capped(spans, limit: 40, expanded: expanded.contains("spans"))
        return VStack(alignment: .leading, spacing: 0) {
            SectionLabel(Copy.Traces.timelineSection).padding(.bottom, CicadaTheme.spacingXS)
            ForEach(capped.shown) { span in spanRow(span) }
            if capped.more > 0 { allLink(capped.more, key: "spans") }
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
            IconButton(systemName: "trash", help: Copy.Traces.deleteSpanHelp, accessibilityLabel: Copy.Traces.deleteItem) {
                Task { await model.delete(spans: [span.id]) }
            }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }

    private func allLink(_ n: Int, key: String) -> some View {
        TextButton(title: Copy.Traces.allCount(n), inline: true, flushLeading: true) { expanded.insert(key) }
    }

    // MARK: - Pieces

    private func dayLabel(_ day: ISODay) -> String { RelativeDay.phrase(day, today: model.today) }

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

/// Search hits across every kept day (a screenshot's words only once screenshots are shown).
private struct TracesHitsList: View {
    let model: TracesBrowserModel

    var body: some View {
        if let hits = model.hits, hits.isEmpty {
            Text(Copy.Traces.noHits).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        } else if let hits = model.hits {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(hits) { hit in row(hit) }
            }
        }
    }

    private func row(_ hit: TraceSearchHit) -> some View {
        let fromScreenshot = hit.kind == "frame"
        let day = ISODay(hit.at).map { RelativeDay.phrase($0, today: model.today) } ?? ""
        let at = TraceClock.parse(hit.at)?.formatted(date: .omitted, time: .shortened) ?? ""
        return HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            Text(Eyebrow.text(day, at)).font(CicadaTheme.metaFont).monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(170), alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(fromScreenshot ? Eyebrow.text(Copy.Traces.readText, hit.app ?? "") : (hit.app ?? ""))
                    .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                let detail = Eyebrow.text(hit.title ?? "", hit.url.flatMap { URL(string: $0)?.host } ?? "")
                if !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                if let snippet = hit.snippet, !snippet.isEmpty, !fromScreenshot || model.unlocked {
                    Text(snippet).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }
}

/// The Traces page's Settings…: Sources' old controls in a sheet — pause, forget, what is recorded, how long, what is
/// never recorded, browsers, titles per app, what is on this Mac — with no "Browse" (the page is it). What joins memory
/// is on the page itself (2026-10-28).
struct TracesSettingsSheet: View {
    let onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(Copy.Traces.settingsTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
                .padding([.horizontal, .top], CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingMD)
            ScrollView {
                TracesControls(showsBrowse: false)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, CicadaTheme.spacingXL)
            }
            HStack {
                Spacer()
                NeutralButton(title: Copy.Traces.done, size: .compact, shortcut: .cancelAction) { onClose() }
            }
            .padding(CicadaTheme.spacingMD)
        }
        .frame(width: CicadaTheme.scaled(560), height: CicadaTheme.scaled(620))
        .background(CicadaTheme.bgBase)
    }
}

/// Sources' Traces row once the page exists (owner 2026-10-26): one line and the way there. Before traces were ever on,
/// Sources keeps the switch itself (`TracesControls`' Turn on…).
struct TracesSourcesLink: View {
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(TraceRecorder.self) private var recorder: TraceRecorder?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let recorder {
                Text(TracesControlsLogic.stateLine(recorder.state, settings: recorder.settings, now: .now))
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(Copy.Traces.onItsPage).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            NeutralButton(title: Copy.Traces.openPage, systemImage: AppTab.traces.icon, size: .compact,
                          help: Copy.Traces.openPageHelp) { router?.pendingTab = .traces }
        }
    }
}
