import SwiftUI

/// R-PP11 — what is selected on a project: one key shared by the band and the sections, so a click on either rings the
/// other (the owner: "make nodes in the timeline clickable").
enum ProjectKey: Hashable, Sendable {
    case item(String), milestone(String), thread(String)

    var id: String {
        switch self {
        case .item(let s): "item:\(s)"
        case .milestone(let s): "milestone:\(s)"
        case .thread(let s): "thread:\(s)"
        }
    }

    /// Which section draws the key's row (a thread in Now, a milestone in Plan, anything else in Lately).
    var section: ProjectSection {
        switch self {
        case .thread: .now
        case .milestone: .plan
        case .item: .lately
        }
    }
}

enum ProjectSection: String, CaseIterable, Sendable { case now, lately, plan, backlog, around }

/// §3.8 / §9 (2026-09-23) / R-PP10 — the band, pure: every mark at the approved mock's coordinates, in units that
/// `ProjectBandView` scales (DR-70). The green is the band's one hue; every mark is a neutral shape in the text ladder
/// (R-PJ21 as the owner settled it); every mark is a button.
struct BandLayout: Equatable {
    enum Lane: Int, CaseIterable { case track, below, above }
    enum Mark: Equatable { case done, said, history, milestoneDone, milestonePlanned, milestoneClosed, ghost, earlier }
    enum Cap: Equatable { case open, done }

    struct Node: Identifiable, Equatable {
        let key: ProjectKey
        let mark: Mark
        let x: CGFloat
        var lane: Lane
        let label: String
        let when: String
        var more = 0
        var id: String { "\(key.id)|\(mark)" }
    }

    struct Thread: Identifiable, Equatable {
        let key: ProjectKey
        let x0: CGFloat
        let x1: CGFloat
        /// The share of the span drawn solid: 1 while heard from, then dashed from its last-heard day once quiet.
        let solid: Double
        let cap: Cap
        let row: Int
        let label: String
        let when: String
        var id: String { key.id }
    }

    struct Tick: Equatable { let x: CGFloat; let label: String }
    struct Bracket: Equatable { let x0: CGFloat; let x1: CGFloat }

    let span: ProgressSpan
    let width: CGFloat
    let months: [Tick]
    let words: [Tick]
    let nodes: [Node]
    let threads: [Thread]
    let brackets: [Bracket]
    let next: Tick?
    let since: String
    let progressWords: String?
    let accessibility: String

    func x(_ day: ISODay) -> CGFloat { CGFloat(span.fraction(day)) * width }
    var todayX: CGFloat { x(span.today) }

    /// ←/→ — every mark left to right; a ghost (a moved milestone's old date) selects its milestone, so it is no stop.
    var order: [ProjectKey] {
        let marks = nodes.filter { $0.mark != .ghost }.map { (x: $0.x, rank: $0.lane.rawValue, key: $0.key) }
        let spans = threads.map { (x: $0.x0, rank: Lane.allCases.count + $0.row, key: $0.key) }
        var seen = Set<ProjectKey>()
        return (marks + spans).sorted { ($0.x, $0.rank) < ($1.x, $1.rank) }.compactMap { seen.insert($0.key).inserted ? $0.key : nil }
    }

    /// DR-68 — ← / → from the selection, clamped; from nothing, the first (→) or the last (←).
    func step(from key: ProjectKey?, delta: Int) -> ProjectKey? {
        let keys = order
        guard !keys.isEmpty else { return nil }
        guard let key, let i = keys.firstIndex(of: key) else { return delta >= 0 ? keys.first : keys.last }
        return keys[min(max(i + delta, 0), keys.count - 1)]
    }

    // The approved mock's coordinates, in units (`ProjectBandView` scales them).
    static let height: CGFloat = 112
    static let inset: CGFloat = 14
    static let trackTop: CGFloat = 22
    static let trackHeight: CGFloat = 10
    static let todayTop: CGFloat = 14
    static let todayHeight: CGFloat = 60
    static let tickTop: CGFloat = 80
    static let monthTop: CGFloat = 86
    static let wordTop: CGFloat = 100
    static let labelTop: CGFloat = -7
    static let threadRows = 2
    static let minGap: CGFloat = 12
    static let longWindowDays = 540
    static let keptDays = 365

    static func y(_ lane: Lane) -> CGFloat {
        switch lane {
        case .track: 27
        case .below: 43
        case .above: 13
        }
    }

    static func threadY(_ row: Int) -> CGFloat { 56 + CGFloat(row) * 12 }

    static func make(_ t: ProjectTimeline, state: ProjectState.Output, width: CGFloat, today: ISODay,
                     locale: Locale = .autoupdatingCurrent) -> BandLayout {
        let items = t.items.filter { $0.kind != "created" }
        var span = ProjectsModel.span(t, planned: state.planned, today: today)
        var earlier: [ProjectItem] = []
        if today - span.start > longWindowDays {
            let kept = today.adding(-keptDays)
            earlier = items.filter { ISODay($0.day).map { $0 < kept } ?? false }
            span = ProgressSpan(start: kept, end: span.end, today: today, planned: span.planned)
        }
        func x(_ day: ISODay) -> CGFloat { CGFloat(span.fraction(day)) * width }
        func absolute(_ day: ISODay) -> String { RelativeDay.absolute(day, today: today, locale: locale) }

        var placed: [Node] = []
        /// R-PP10 — the preferred lane, then the others; a mark with no free lane folds into its nearest neighbour.
        func place(_ node: Node, prefer: Lane) {
            for lane in [prefer] + Lane.allCases.filter({ $0 != prefer })
            where !placed.contains(where: { $0.lane == lane && abs($0.x - node.x) < minGap }) {
                var n = node
                n.lane = lane
                placed.append(n)
                return
            }
            if let i = placed.indices.min(by: { abs(placed[$0].x - node.x) < abs(placed[$1].x - node.x) }) {
                placed[i].more += 1
            }
        }

        // Milestones own the track (§3.8).
        var brackets: [Bracket] = []
        let milestones = t.milestones.filter { $0.source != "expectedEnd" }
        for m in milestones.sorted(by: { ($0.doneOn ?? $0.target ?? "~") < ($1.doneOn ?? $1.target ?? "~") }) {
            let st = state.milestone(m.slug) ?? ProjectState.milestoneState(m, today: today)
            let at: ISODay?
            let mark: Mark
            let words: (ISODay) -> String
            switch st.state {
            case "done":
                at = ISODay(m.doneOn) ?? ISODay(m.target)
                mark = .milestoneDone
                words = { Copy.Projects.milestoneDoneOn(absolute($0)) }
            case "passed-no-word":
                at = ISODay(m.target)
                mark = .milestoneClosed
                words = { Copy.Projects.milestonePassed(absolute($0)) }
            case "missed":
                at = ISODay(m.target)
                mark = .milestoneClosed
                words = { Copy.Projects.milestoneMissed(absolute($0)) }
            case "overdue":
                at = ISODay(m.target)
                mark = .milestonePlanned
                words = { Copy.Projects.milestoneOverdue(absolute($0)) }
            case "upcoming":
                at = ISODay(m.target)
                mark = .milestonePlanned
                words = { Copy.Projects.milestoneUpcoming(absolute($0), RelativeDay.distance($0, today: today)) }
            default:
                continue   // someday has no date to stand on; a dropped milestone leaves nothing planned
            }
            guard let at, at >= span.start else { continue }
            place(Node(key: .milestone(m.slug), mark: mark, x: x(at), lane: .track, label: m.name, when: words(at)),
                  prefer: .track)
            if mark == .milestonePlanned, let old = ProjectsModel.earlierTarget(m), old >= span.start {
                let movedOn = ISODay(m.chain.first?.validFrom).map(absolute) ?? ""
                place(Node(key: .milestone(m.slug), mark: .ghost, x: x(old), lane: .track,
                           label: Copy.Projects.earlierTarget(m.name), when: Copy.Projects.movedOn(absolute(old), movedOn)),
                      prefer: .track)
                brackets.append(Bracket(x0: min(x(old), x(at)), x1: max(x(old), x(at))))
            }
        }
        if let oldest = earlier.min(by: { ($0.day ?? "") < ($1.day ?? "") }), let day = ISODay(oldest.day) {
            place(Node(key: .item(oldest.id), mark: .earlier, x: 0, lane: .track,
                       label: Copy.Projects.earlier(earlier.count), when: absolute(day)), prefer: .track)
        }

        // Happenings prefer the track, then moments and history bullets prefer below; an ongoing happening is a thread.
        let dated = items.compactMap { item -> (ProjectItem, ISODay)? in
            guard let day = ISODay(item.day), day >= span.start else { return nil }
            return (item, day)
        }.sorted { $0.1 < $1.1 }
        for (item, day) in dated where item.kind == "happening" && item.status != "ongoing" {
            let words = ProjectsModel.firstWords(item.text)
            place(Node(key: .item(item.id), mark: .done, x: x(day), lane: .track, label: words,
                       when: RelativeDay.phrase(day, today: today, locale: locale)), prefer: .track)
        }
        for (item, day) in dated where item.kind == "moment" || item.kind == "history" {
            let words = ProjectsModel.firstWords(item.text)
            place(Node(key: .item(item.id), mark: item.kind == "moment" ? .said : .history, x: x(day), lane: .below,
                       label: words, when: RelativeDay.phrase(day, today: today, locale: locale)), prefer: .below)
        }

        // Threads: the open ones first (to today, an open cap), then a settled one (to its end, a closed cap).
        var threads: [Thread] = []
        for (row, th) in t.now.threads.prefix(threadRows).enumerated() {
            guard let since = ISODay(th.since) else { continue }
            let heard = ISODay(th.lastHeard) ?? since
            let quietDays = state.thread(th.claimId)?.quietDays ?? (today - heard)
            let quiet = quietDays > state.quietThreshold
            let solid = quiet && today > since ? Double(heard - since) / Double(today - since) : 1
            let when = quiet ? "\(Copy.Projects.sinceDay(absolute(since))) · \(Copy.Projects.quietDays(quietDays))"
                : (since == today ? Copy.Projects.startedToday : Copy.Projects.sinceDay(absolute(since)))
            threads.append(Thread(key: .thread(th.claimId), x0: x(max(since, span.start)), x1: x(today),
                                  solid: min(max(solid, 0), 1), cap: .open, row: row, label: th.text, when: when))
        }
        for item in items where threads.count < threadRows && item.kind == "happening" && item.status == "ongoing" {
            guard let to = ISODay(item.claim?.validTo), let from = ISODay(item.claim?.validFrom ?? item.day) else { continue }
            threads.append(Thread(key: .item(item.id), x0: x(max(from, span.start)), x1: x(to), solid: 1, cap: .done,
                                  row: threads.count, label: item.text, when: Copy.Projects.ongoingUntil(absolute(to))))
        }

        // Months, plus the start's month when the first tick sits past 7 % (the mock).
        var months: [Tick] = []
        func monthStart(_ year: Int, _ month: Int) -> ISODay {
            month > 12 ? ISODay(year: year + 1, month: month - 12, day: 1) : ISODay(year: year, month: month, day: 1)
        }
        let s = span.start.civil
        var tick = s.day == 1 ? span.start : monthStart(s.year, s.month + 1)
        while tick <= span.end {
            months.append(Tick(x: x(tick), label: RelativeDay.month(tick, locale: locale)))
            let c = tick.civil
            tick = monthStart(c.year, c.month + 1)
        }
        if (months.first?.x ?? .infinity) > width * 0.07 {
            months.insert(Tick(x: 0, label: RelativeDay.month(span.start, locale: locale)), at: 0)
        }
        let words = RelativeDay.bandWords(spanDays: span.days).compactMap { w -> Tick? in
            let day = today.adding(w.offset)
            guard day >= span.start, day <= span.end else { return nil }
            let px = x(day)
            return px > width * 0.08 && px < width * 0.94 ? Tick(x: px, label: w.text) : nil
        }
        let next = state.next.flatMap { slug in milestones.first { $0.slug == slug } }.flatMap { m in
            ISODay(m.target).map { Tick(x: x($0), label: Copy.Projects.nextMark(m.name, RelativeDay.distance($0, today: today))) }
        }

        return BandLayout(
            span: span, width: width, months: months, words: words, nodes: placed, threads: threads, brackets: brackets,
            next: next, since: Copy.Projects.since(absolute(span.start)),
            progressWords: state.planned ? Copy.Projects.doneOf(state.progress) : nil,
            accessibility: Copy.Projects.bandLabel(t.project.name, planned: state.planned, progress: state.progress,
                                                   today: RelativeDay.spoken(today, locale: locale)))
    }
}

/// §3.8 — the band, drawn: a `Canvas` for the track, the green, the open end, the brackets, the ticks and the "You,
/// today" marker; every mark a real `Button` over it (the owner's "clickable"), with an instant hover tooltip whose text
/// twin is the mark's accessibility label (DR-69). Selection is a `textPrimary` ring, never the accent (DR-5).
struct ProjectBandView: View {
    let layout: BandLayout
    let selected: ProjectKey?
    let isFocused: Bool
    let pick: (ProjectKey) -> Void

    @State private var hovered: String?

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        ZStack(alignment: .topLeading) {
            Canvas { context, _ in drawStatic(context) }
                .frame(width: layout.width, height: s(BandLayout.height))
                .accessibilityHidden(true)
            labels
            ForEach(layout.threads) { thread($0) }
            ForEach(layout.nodes) { node($0) }
            tooltip
        }
        .frame(width: layout.width, height: s(BandLayout.height), alignment: .topLeading)
        .padding(.horizontal, s(BandLayout.inset))
        .padding(.top, s(8))
        .overlay {
            if isFocused {
                CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).strokeBorder(CicadaTheme.focusRing, lineWidth: 2)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(layout.accessibility)
    }

    private func drawStatic(_ context: GraphicsContext) {
        let track = CGRect(x: 0, y: s(BandLayout.trackTop), width: layout.width, height: s(BandLayout.trackHeight))
        let radius = track.height / 2
        let todayX = layout.todayX
        if layout.span.planned {
            context.fill(Path(roundedRect: track, cornerRadius: radius), with: .color(CicadaTheme.bgBadge))
        } else {
            var end = Path()
            end.move(to: CGPoint(x: todayX + 2, y: track.midY))
            end.addLine(to: CGPoint(x: layout.width, y: track.midY))
            context.stroke(end, with: .color(CicadaTheme.progressOpenEnd), style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
        }
        let filled = CGRect(x: 0, y: track.minY, width: max(todayX, track.height), height: track.height)
        context.fill(Path(roundedRect: filled, cornerRadius: radius), with: .color(CicadaTheme.progressFill))
        for b in layout.brackets {
            var arc = Path()
            let top = track.minY - s(8)
            arc.move(to: CGPoint(x: b.x0, y: track.minY - s(2)))
            arc.addLine(to: CGPoint(x: b.x0, y: top))
            arc.addLine(to: CGPoint(x: b.x1, y: top))
            arc.addLine(to: CGPoint(x: b.x1, y: track.minY - s(2)))
            context.stroke(arc, with: .color(CicadaTheme.textTertiary), style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
        }
        for m in layout.months {
            context.fill(Path(CGRect(x: m.x, y: s(BandLayout.tickTop), width: 1, height: s(4))),
                         with: .color(CicadaTheme.textTertiary))
        }
        // "You, today" — 2 units of textPrimary on a bgBase knockout: the marker is not the accent (§3.8, R-PJ21).
        let marker = CGRect(x: todayX - 1, y: s(BandLayout.todayTop), width: 2, height: s(BandLayout.todayHeight))
        context.fill(Path(roundedRect: marker.insetBy(dx: -1.5, dy: -1.5), cornerRadius: 2), with: .color(CicadaTheme.bgBase))
        context.fill(Path(roundedRect: marker, cornerRadius: 1), with: .color(CicadaTheme.textPrimary))
    }

    private var labels: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(layout.months.enumerated()), id: \.offset) { _, m in
                edgeLabel(m.label, x: m.x, y: s(BandLayout.monthTop))
            }
            ForEach(Array(layout.words.enumerated()), id: \.offset) { _, w in
                edgeLabel(w.label, x: w.x, y: s(BandLayout.wordTop))
            }
            Text(Copy.Projects.youToday)
                .font(CicadaTheme.font(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize()
                .position(x: layout.todayX, y: s(BandLayout.labelTop + 7))
            // The next milestone's words sit over its diamond — hidden when they would run into "You, today".
            if let next = layout.next, abs(next.x - layout.todayX) > s(72) {
                edgeLabel(next.label, x: next.x, y: s(BandLayout.labelTop))
            }
        }
        .accessibilityHidden(true)
    }

    /// A label centred on `x`, pulled inside the band at either end so it is never clipped.
    private func edgeLabel(_ text: String, x: CGFloat, y: CGFloat) -> some View {
        let nearStart = x < s(24)
        let nearEnd = x > layout.width - s(24)
        return Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize()
            .frame(width: s(96), alignment: nearStart ? .leading : (nearEnd ? .trailing : .center))
            .position(x: nearStart ? x + s(48) : (nearEnd ? x - s(48) : x), y: y + s(7))
    }

    private func node(_ n: BandLayout.Node) -> some View {
        Button { pick(n.key) } label: {
            BandMark(mark: n.mark, selected: selected == n.key && n.mark != .ghost)
                .frame(width: s(20), height: s(20))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .position(x: n.x, y: s(BandLayout.y(n.lane)))
        .onHover { inside in hovered = inside ? n.id : (hovered == n.id ? nil : hovered) }
        .accessibilityLabel(accessibility(n))
        .accessibilityAddTraits(selected == n.key ? [.isSelected] : [])
    }

    private func accessibility(_ n: BandLayout.Node) -> String {
        let base: String
        switch n.mark {
        case .done, .earlier: base = Copy.Projects.happened(n.label, n.when)
        case .said: base = Copy.Projects.saidHere(n.label, n.when)
        case .history: base = Copy.Projects.fromHistory(n.label, n.when)
        case .milestoneDone, .milestonePlanned, .milestoneClosed, .ghost: base = Copy.Projects.milestoneMark(n.label, n.when)
        }
        return n.more > 0 ? "\(base), \(Copy.Projects.moreHere(n.more))" : base
    }

    private func thread(_ t: BandLayout.Thread) -> some View {
        let length = max(t.x1 - t.x0, 0)
        let isSelected = selected == t.key
        return Button { pick(t.key) } label: {
            ZStack(alignment: .leading) {
                Circle().fill(CicadaTheme.textSecondary).frame(width: s(6), height: s(6)).offset(x: -s(3))
                Capsule().fill(CicadaTheme.textSecondary).frame(width: length * t.solid, height: 2)
                if t.solid < 1 {
                    MidLine()
                        .stroke(CicadaTheme.textSecondary.opacity(0.55), style: StrokeStyle(lineWidth: 2, dash: [3, 3]))
                        .frame(width: length * (1 - t.solid), height: 2)
                        .offset(x: length * t.solid)
                }
                ThreadCap(cap: t.cap, selected: isSelected).offset(x: length - s(5))
            }
            .frame(width: length, height: s(16), alignment: .leading)
            .padding(.horizontal, s(8))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .position(x: t.x0 + length / 2, y: s(BandLayout.threadY(t.row)))
        .onHover { inside in hovered = inside ? t.id : (hovered == t.id ? nil : hovered) }
        .accessibilityLabel(Copy.Projects.inMotion(t.label, t.when))
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
    }

    /// The hover words: the sentence's first words and its date, on a floating surface (DR-10), instant — a mark this
    /// small needs its words the moment the pointer arrives.
    @ViewBuilder
    private var tooltip: some View {
        if let id = hovered, let tip = tip(id) {
            HStack(spacing: s(6)) {
                Text(tip.label).foregroundStyle(CicadaTheme.textPrimary)
                Text(tip.when).foregroundStyle(CicadaTheme.textTertiary)
            }
            .font(CicadaTheme.metaMediumFont)
            .lineLimit(1)
            .padding(.horizontal, s(8))
            .frame(height: s(24))
            .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .fixedSize()
            .position(x: min(max(tip.x, s(90)), max(layout.width - s(90), s(90))), y: tip.y - s(22))
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }

    private func tip(_ id: String) -> (label: String, when: String, x: CGFloat, y: CGFloat)? {
        if let n = layout.nodes.first(where: { $0.id == id }) {
            let when = n.more > 0 ? "\(n.when) · \(Copy.Projects.moreHere(n.more))" : n.when
            return (n.label, when, n.x, s(BandLayout.y(n.lane)))
        }
        if let t = layout.threads.first(where: { $0.id == id }) {
            return (ProjectsModel.firstWords(t.label), t.when, t.x1, s(BandLayout.threadY(t.row)))
        }
        return nil
    }
}

/// One mark: a shape in the text ladder with a 2-unit `bgBase` knockout, so a mark inside the green reads (§3.8);
/// selected, a `textPrimary` ring (R-PP11).
struct BandMark: View {
    let mark: BandLayout.Mark
    let selected: Bool

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        switch mark {
        case .done: dot(filled: true)
        case .said: dot(filled: false)
        case .history:
            CicadaTheme.shape(1).fill(CicadaTheme.textTertiary)
                .frame(width: s(3), height: s(12))
                .background(CicadaTheme.shape(2).fill(CicadaTheme.bgBase).padding(-2))
                .overlay { if selected { CicadaTheme.shape(2).stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
        case .milestoneDone: diamond(fill: CicadaTheme.textPrimary, stroke: nil, dashed: false, size: 11)
        case .milestonePlanned: diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textSecondary, dashed: false, size: 11)
        case .milestoneClosed:
            diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textSecondary, dashed: false, size: 11)
                .overlay { Rectangle().fill(CicadaTheme.textSecondary).frame(width: 1.5, height: s(17)) }
        case .ghost: diamond(fill: CicadaTheme.bgBase, stroke: CicadaTheme.textTertiary, dashed: true, size: 10)
        case .earlier:
            Text("…").font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func dot(filled: Bool) -> some View {
        Circle()
            .fill(filled ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if !filled { Circle().strokeBorder(CicadaTheme.textPrimary, lineWidth: 1.5) } }
            .frame(width: s(8), height: s(8))
            .background(Circle().fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { Circle().stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
    }

    private func diamond(fill: Color, stroke: Color?, dashed: Bool, size: CGFloat) -> some View {
        let shape = CicadaTheme.shape(2)
        return shape.fill(fill)
            .overlay {
                if let stroke {
                    shape.strokeBorder(stroke, style: StrokeStyle(lineWidth: 1.5, dash: dashed ? [2, 2] : []))
                }
            }
            .frame(width: s(size), height: s(size))
            .background(shape.fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { shape.stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
            .rotationEffect(.degrees(45))
    }
}

/// A thread's end at today: open (a ring) while it runs, filled once a successor settled it.
struct ThreadCap: View {
    let cap: BandLayout.Cap
    let selected: Bool

    var body: some View {
        let side = CicadaTheme.scaled(10)
        Circle()
            .fill(cap == .done ? CicadaTheme.textPrimary : CicadaTheme.bgBase)
            .overlay { if cap == .open { Circle().strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5) } }
            .frame(width: side, height: side)
            .background(Circle().fill(CicadaTheme.bgBase).padding(-2))
            .overlay { if selected { Circle().stroke(CicadaTheme.textPrimary, lineWidth: 1.5).padding(-3.5) } }
    }
}
