import SwiftUI

// Projects v3 (decisions 9, 10 and 17, owner 2026-10-28; DR-81 as proposed in the redesign, DR-38, DR-45, DR-74,
// §3.8) — the project page with no folds. A section with nothing in it is not drawn; a section with something is open
// and holds at most `ProjectOpen.cap` rows; more is a plain "All N" that swaps the column to the full list (Esc back),
// never an in-place expansion. The pulse's bars are neutral ink: the band's green stays its one hue (§3.8).

/// The open sections' shared rules, pure.
enum ProjectOpen {
    /// At most this many rows in an open section or a panel block before "All N".
    static let cap = 5

    /// What the column shows when an "All N" was clicked: one section's full list in place of the card's sections.
    enum Full: String, Hashable, Sendable {
        case inMotion, comingUp, timeline, pages, conversations, influences
    }

    /// The Timeline's rows: the story's items (moments, happenings, history — never `created`, the foot line) and
    /// every milestone marked done, as a filled diamond with its "Milestone done" Tag. Newest first; undated last.
    enum TimelineEntry: Identifiable, Equatable {
        case item(ProjectItem)
        case milestone(ProjectMilestone)

        var id: String {
            switch self {
            case .item(let i): ProjectKey.item(i.id).id
            case .milestone(let m): ProjectKey.milestone(m.slug).id
            }
        }

        var day: String? {
            switch self {
            case .item(let i): i.day
            case .milestone(let m): m.doneOn ?? m.target
            }
        }

        var key: ProjectKey {
            switch self {
            case .item(let i): .item(i.id)
            case .milestone(let m): .milestone(m.slug)
            }
        }
    }

    static func timeline(_ t: ProjectTimeline) -> [TimelineEntry] {
        let items = t.items.filter { $0.kind != "created" }.map(TimelineEntry.item)
        let done = t.milestones.filter { $0.status == "done" && $0.source != "expectedEnd" }.map(TimelineEntry.milestone)
        // A stable merge: the server's order among items is kept (newest first, its own tie-breaks).
        return (items + done).enumerated().sorted { a, b in
            switch (a.element.day, b.element.day) {
            case let (x?, y?) where x != y: return x > y
            case (.some, nil): return true
            case (nil, .some): return false
            default: return a.offset < b.offset
            }
        }.map(\.element)
    }

    /// Coming up: the planned milestones (by target, undated last), then the backlog still open or in progress.
    struct ComingUp: Equatable {
        let milestones: [ProjectPlan.Row]
        let backlog: [BacklogItemSummary]
        var count: Int { milestones.count + backlog.count }
        var isEmpty: Bool { count == 0 }

        /// The first `cap` rows, milestones first.
        func capped(_ cap: Int = ProjectOpen.cap) -> ComingUp {
            let m = Array(milestones.prefix(cap))
            return ComingUp(milestones: m, backlog: Array(backlog.prefix(max(cap - m.count, 0))))
        }
    }

    static func comingUp(_ t: ProjectTimeline, backlog: BacklogList?, today: ISODay) -> ComingUp {
        let planned = ProjectPlan.rows(t.milestones.filter { $0.status == "planned" && $0.source != "expectedEnd" },
                                       today: today)
        let open = (backlog?.items ?? []).filter { $0.backlogStatus == .open || $0.backlogStatus == .doing }
        return ComingUp(milestones: planned, backlog: open)
    }

    /// Which section draws a key's row: a thread in In motion, a planned milestone in Coming up, a done milestone and
    /// every item in the Timeline.
    static func full(for key: ProjectKey, in t: ProjectTimeline) -> Full {
        switch key {
        case .thread: return .inMotion
        case .item: return .timeline
        case .milestone(let slug):
            return t.milestones.first { $0.slug == slug }?.status == "planned" ? .comingUp : .timeline
        }
    }

    /// Whether a key's row is among the capped rows the open section draws (else picking it opens the full list).
    static func isShown(_ key: ProjectKey, in t: ProjectTimeline, state: ProjectState.Output, backlog: BacklogList?,
                        today: ISODay) -> Bool {
        switch full(for: key, in: t) {
        case .inMotion:
            return ProjectStory.nowThreads(t, state: state).prefix(cap).contains { ProjectKey.thread($0.claimId) == key }
        case .comingUp:
            return comingUp(t, backlog: backlog, today: today).capped().milestones
                .contains { ProjectKey.milestone($0.milestone.slug) == key }
        default:
            return timeline(t).prefix(cap).contains { $0.key == key }
        }
    }
}

/// An open section's head: its label and count (DR-20's `SectionLabel`), and — only when it holds more than it shows —
/// a plain "All N" on the right that opens the full list. Never a chevron (DR-81).
struct ProjectOpenLabel: View {
    let title: String
    let count: Int
    var all: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            SectionLabel(count > 0 ? Copy.ProjectsOpen.titled(title, count) : title)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let all, count > ProjectOpen.cap {
                TextButton(title: Copy.ProjectsOpen.all(count), help: Copy.ProjectsOpen.allHelp(title), inline: true,
                           action: all)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
    }
}

/// The full list's head: Back (Esc) and the section's title with its count (DR-74's column head words, the 17 pt
/// heading face never; the H1 is the project's).
struct ProjectFullHead: View {
    let title: String
    let count: Int
    let back: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            TextButton(title: "‹ " + Copy.ProjectsOpen.back, help: Copy.ProjectsOpen.backHelp, flushLeading: true,
                       action: back)
            Text(Copy.ProjectsOpen.titled(title, count))
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Pulse

/// Decision 9 — three counted facts side by side: the last 4 weeks (a line of words over four neutral weekly bars),
/// what it waits on, what has gone quiet. A fact with nothing to say is not drawn; with none, the section is not drawn.
struct ProjectPulseView: View {
    let pulse: ProjectPulse.Output
    let today: ISODay
    let pick: (ProjectKey) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.ProjectsOpen.pulse)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .help(Copy.ProjectsOpen.pulseHelp)
            HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
                if pulse.conversations > 0 || pulse.done > 0 {
                    column(Copy.ProjectsOpen.lastFourWeeks) {
                        Text(Copy.ProjectsOpen.pulseCounts(conversations: pulse.conversations, done: pulse.done))
                            .font(CicadaTheme.bodyFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textPrimary)
                        PulseBars(weeks: pulse.weeks)
                            .help(Copy.ProjectsOpen.weeksHelp(pulse.weeks))
                    }
                }
                if let w = pulse.waiting.first {
                    column(Copy.ProjectsOpen.waitingOn) {
                        Button { pick(.thread(w.claimId)) } label: {
                            Text(Copy.ProjectsOpen.waitingLine(w.who, w.text))
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                        }
                        .buttonStyle(.cicadaPlain)
                        Text(meta(since: w.since, more: pulse.waitingTotal - 1))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                if let q = pulse.quiet.first {
                    column(Copy.ProjectsOpen.goneQuiet) {
                        Button { pick(.thread(q.claimId)) } label: {
                            Text(Copy.ProjectsOpen.quietLine(q.text, weeks: q.quietDays / 7, days: q.quietDays))
                                .font(CicadaTheme.bodyFont)
                                .monospacedDigit()
                                .foregroundStyle(CicadaTheme.textPrimary)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                        }
                        .buttonStyle(.cicadaPlain)
                        if let since = ISODay(q.since) {
                            Text(Copy.ProjectsOpen.startedNothingSince(RelativeDay.absolute(since, today: today)))
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
        }
        .accessibilityElement(children: .contain)
    }

    private func meta(since: String, more: Int) -> String {
        let day = ISODay(since).map { Copy.ProjectsOpen.since(RelativeDay.absolute($0, today: today)) } ?? ""
        return more > 0 ? Eyebrow.text(day, Copy.ProjectsOpen.moreWaiting(more)) : day
    }

    private func column<C: View>(_ label: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            Text(label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

/// Four weekly bars in the text ladder — never a hue (§3.8: the band's green is the page's one colour). The newest
/// week is the darkest, the rest a step lighter; an empty week keeps a 2 pt stub so the four always read as four.
struct PulseBars: View {
    let weeks: [Int]

    var body: some View {
        let peak = max(weeks.max() ?? 0, 1)
        let tall = CicadaTheme.scaled(20)
        HStack(alignment: .bottom, spacing: CicadaTheme.scaled(4)) {
            ForEach(Array(weeks.enumerated()), id: \.offset) { i, n in
                CicadaTheme.shape(1.5)
                    .fill(i == weeks.count - 1 ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(14),
                           height: max(CicadaTheme.scaled(2), tall * CGFloat(n) / CGFloat(peak)))
            }
        }
        .frame(height: tall, alignment: .bottom)
        .accessibilityHidden(true)
    }
}

// MARK: - Coming up and the Timeline's own rows

/// A backlog item in Coming up: a hollow square, its title and "backlog"; a click opens it as the third column (R-B21).
struct ProjectBacklogLine: View {
    let item: BacklogItemSummary
    let selected: Bool
    let open: (String) -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            CicadaTheme.shape(2)
                .strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5)
                .frame(width: CicadaTheme.scaled(10), height: CicadaTheme.scaled(10))
                .frame(width: CicadaTheme.scaled(14))
                .accessibilityHidden(true)
            Text(item.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
            Text("· " + Copy.ProjectsOpen.backlogTag).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { open(item.id) }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

/// A milestone marked done, as the Timeline reads it: the band's filled diamond, its name, a "Milestone done" Tag
/// (DR-44) and its day.
struct ProjectMilestoneDoneRow: View {
    let milestone: ProjectMilestone
    let today: ISODay
    let selected: Bool
    let pick: (ProjectKey) -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            PlanDiamond(style: .filled)
            Text(milestone.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(2)
            Tag(text: Copy.ProjectsOpen.milestoneDone)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let day = ISODay(milestone.doneOn ?? milestone.target) {
                Text(RelativeDay.absolute(day, today: today))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(.milestone(milestone.slug)) }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

// MARK: - Pages in this project

/// Decision 10 — the knowledge panel's first block: the pages that are part of the project (what the person said, the
/// ones they or an agent tied by hand) with Add, and on each row "Not part of it" (on hover and in its menu). An agent's
/// proposal leads, with Add beside it. A row opens the page's card beside the project (R-PP17).
struct ProjectPagesBlock: View {
    let timeline: ProjectTimeline
    let blocked: Bool
    var limit: Int? = ProjectOpen.cap
    let openEntity: (String) -> Void
    let add: () -> Void
    let take: (ProjectPageRow) -> Void
    let remove: (ProjectPageRow) -> Void
    var all: (() -> Void)? = nil

    @State private var hovered: String?

    private var partOf: Int { timeline.pagesTotal - (timeline.pageCounts["proposed"] ?? 0) }

    var body: some View {
        let rows = limit.map { Array(timeline.pages.prefix($0)) } ?? timeline.pages
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            HStack {
                Text(Copy.ProjectsOpen.pages(partOf)).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                TextButton(title: Copy.ProjectsOpen.add, help: Copy.ProjectsOpen.addPageHelp, inline: true, action: add)
                    .disabled(blocked)
            }
            ForEach(rows) { row($0) }
            let line = Copy.ProjectsOpen.pagesLine(timeline.pageCounts)
            if !line.isEmpty || (all != nil && timeline.pagesTotal > rows.count) {
                HStack {
                    Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        .help(Copy.ProjectsOpen.pagesHelp)
                    Spacer()
                    if let all, timeline.pagesTotal > rows.count {
                        TextButton(title: Copy.ProjectsOpen.all(timeline.pagesTotal), inline: true, action: all)
                    }
                }
            }
        }
    }

    private func row(_ p: ProjectPageRow) -> some View {
        let hovering = hovered == p.id
        return HStack(spacing: CicadaTheme.spacingSM) {
            TypeDot(type: EntityType(rawValue: p.type ?? "") ?? .concept)
            Text(p.name).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
            if !p.rolePhrase.isEmpty {
                Text("· " + p.rolePhrase).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: CicadaTheme.spacingXS)
            if p.isProposed {
                Text(Copy.ProjectsOpen.suggestedBy(p.by ?? "agent"))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                TextButton(title: Copy.ProjectsOpen.takeIt, help: Copy.ProjectsOpen.takeItHelp, inline: true) { take(p) }
                    .disabled(blocked)
                TextButton(title: Copy.ProjectsOpen.notPartOfIt, help: Copy.ProjectsOpen.notPartOfItHelp,
                           inline: true) { remove(p) }
                    .disabled(blocked)
            } else if hovering && !blocked {
                TextButton(title: Copy.ProjectsOpen.notPartOfIt, help: Copy.ProjectsOpen.notPartOfItHelp,
                           inline: true) { remove(p) }
            } else if p.tie == "user" {
                Tag(text: Copy.ProjectsOpen.youTiedIt)
            } else if p.tie == "agent" {
                Tag(text: Copy.ProjectsOpen.agentTiedIt(p.by ?? "agent"))
            } else if p.count > 0 {
                Text(UsageFormat.count(p.count)).font(CicadaTheme.metaFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(22))
        .contentShape(Rectangle())
        .onTapGesture { openEntity(p.id) }
        .onHover { hovered = $0 ? p.id : (hovered == p.id ? nil : hovered) }
        .contextMenu {
            if p.isProposed { Button(Copy.ProjectsOpen.takeIt) { take(p) }.disabled(blocked) }
            Button(Copy.ProjectsOpen.notPartOfIt) { remove(p) }.disabled(blocked)
        }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isButton)
        .help(p.fact.isEmpty ? p.name : Eyebrow.text(p.name, p.fact))
    }
}

/// Add a page (decision 10): one field, the pages already in memory that match it as option rows, one tap adds
/// (DR-42). Nothing new is made here — a name that matches no page says so (promotion stays Sleep's rule).
struct AddProjectPageSheet: View {
    let candidates: [(id: String, name: String, type: String)]
    let submit: (_ id: String, _ name: String, _ type: String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @FocusState private var focused: Bool

    private var matches: [(id: String, name: String, type: String)] {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else { return [] }
        return Array(candidates.filter { QuickMatch.matches(q, fields: [QuickMatch.Field($0.name,
                                                                                         weight: QuickMatch.Weight.name)]) }
            .prefix(6))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.ProjectsOpen.addPageTitle).font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22)).foregroundStyle(CicadaTheme.textPrimary)
            TextField("", text: $text)
                .focused($focused)
                .cicadaField(isFocused: focused, prompt: Copy.ProjectsOpen.addPagePlaceholder, isEmpty: text.isEmpty)
                .onAppear { focused = true }
                .onSubmit { if let first = matches.first { pick(first) } }
            ForEach(matches, id: \.id) { m in
                Button { pick(m) } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        TypeDot(type: EntityType(rawValue: m.type) ?? .concept)
                        Text(m.name).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                        Spacer()
                    }
                    .padding(CicadaTheme.scaled(10))
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
            }
            if matches.isEmpty && text.trimmingCharacters(in: .whitespaces).count >= 2 {
                Text(Copy.ProjectsOpen.noPageMatches).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            HStack { Spacer(); NeutralButton(title: Copy.ProjectsMine.cancel, shortcut: .cancelAction) { dismiss() } }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(440))
        .background(CicadaTheme.bgBase)
    }

    private func pick(_ m: (id: String, name: String, type: String)) {
        submit(m.id, m.name, m.type)
        dismiss()
    }
}

/// A pending Add or "Not part of it", painted over the timeline until the server's answer holds it (ruling 45's paint
/// rule): a removal leaves the list, an Add makes the person's tie (a proposal they took, or a new row by its name).
enum ProjectPagesPaint {
    static func apply(_ t: ProjectTimeline, entity: String, name: String?, type: String?, remove: Bool) -> ProjectTimeline {
        var t = t
        let before = t.pages.first { $0.id == entity }
        if remove {
            guard let before else { return t }
            t.pages.removeAll { $0.id == entity }
            t.pagesTotal = max(0, t.pagesTotal - 1)
            t.pageCounts[before.tie] = max(0, (t.pageCounts[before.tie] ?? 0) - 1)
            return t
        }
        if let before {
            guard before.tie != "user" else { return t }
            t.pageCounts[before.tie] = max(0, (t.pageCounts[before.tie] ?? 0) - 1)
            t.pages.removeAll { $0.id == entity }
            var row = before
            row.tie = "user"
            row.by = "user"
            t.pages.insert(row, at: t.pages.firstIndex { $0.tie != "proposed" } ?? t.pages.count)
        } else {
            t.pages.insert(ProjectPageRow(id: entity, name: name ?? entity, type: type, tie: "user", by: "user"),
                           at: t.pages.firstIndex { $0.tie != "proposed" } ?? t.pages.count)
            t.pagesTotal += 1
        }
        t.pageCounts["user", default: 0] += 1
        return t
    }
}

// MARK: - Suggested, as one line and as a column

/// Decision 9 — the list's Suggested is one line, "N suggested by Cicada · Review", which opens the suggestions as the
/// detail column. Never a fold (DR-81).
struct ProjectsSuggestedLine: View {
    let count: Int
    let selected: Bool
    let review: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.ProjectsOpen.suggestedLine(count))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: Copy.ProjectsOpen.review, help: Copy.ProjectsOpen.reviewHelp, inline: true, action: review)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

/// The suggestions as the detail column (DR-74's head): text tabs Suggested · Not mine (DR-45), each suggestion with
/// where it came from and its two neutral buttons (DR-40). Nothing here deletes anything.
struct ProjectsSuggestedColumn: View {
    let suggested: [SuggestedProject]
    let blocked: Bool
    let gutter: CGFloat
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let accept: (SuggestedProject) -> Void
    let dismiss: (SuggestedProject) -> Void

    enum Tab: Hashable { case live, dismissed }
    @State private var tab: Tab? = .live

    var body: some View {
        let live = suggested.filter { !$0.dismissed }
        let gone = suggested.filter(\.dismissed)
        let rows = tab == .dismissed ? gone : live
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            DetailHeader(title: Copy.ProjectsOpen.suggestedTitle, blurb: Copy.ProjectsOpen.suggestedBlurb,
                         backLabel: hiddenListCount.map { Copy.Projects.projectsBack($0) }, onShowList: onShowList,
                         closeHelp: Copy.ProjectsOpen.closeSuggested, onClose: onClose)
            if !gone.isEmpty {
                TextTabs(tabs: [TextTab(id: Tab.live, label: Copy.ProjectsOpen.suggestedTab, count: live.count),
                                TextTab(id: Tab.dismissed, label: Copy.ProjectsOpen.dismissedTab, count: gone.count)],
                         selection: Binding(get: { tab }, set: { tab = $0 ?? .live }))
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    if rows.isEmpty {
                        Text(Copy.ProjectsOpen.noneSuggested)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    ForEach(rows) { s in
                        SuggestedProjectRow(suggestion: s, blocked: blocked, accept: { accept(s) },
                                            dismiss: s.dismissed ? nil : { dismiss(s) })
                    }
                }
                .padding(.bottom, CicadaTheme.spacingLG)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
    }
}
