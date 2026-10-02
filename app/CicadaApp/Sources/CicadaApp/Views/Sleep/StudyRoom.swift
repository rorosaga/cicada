import SwiftUI
import UniformTypeIdentifiers

/// VoiceOver's order through the default view (Track Z §11): the sentence,
/// the worm, the window, the wall clock, the lamp, the spines (largest first), the control,
/// the whisper line, then Details. One table, read by every element that
/// sets a priority, so the order can be reviewed in one place.
///
/// **Two levels, because a sort priority only orders siblings inside one
/// accessibility container.** The room card is a `.contain` container
/// (sentence → room → control → whisper; the strip, when shown, keeps the
/// default 0 and reads last). The room is its own `.contain` container inside
/// it (worm → window → clock → lamp → the pile's container, whose spines order
/// themselves largest first). Details sits **outside** the card and carries
/// no priority, so it follows in document order. A priority of 1 on it would
/// sort it ahead of the page title and the whole card, because the page's
/// `VStack` is not a container.
///
/// The window, lamp and spine rows are declared now and read by the tasks
/// that make those props controls (Z6, Z8) — Z-P14: no hotspot ships without
/// the thing it opens, but the order is decided once, here.
enum RoomA11yOrder {
    // Inside the room card.
    static let sentence: Double = 4
    static let room: Double = 3
    static let control: Double = 2
    static let whisper: Double = 1
    // Inside the room.
    static let worm: Double = 4
    static let window: Double = 3
    static let clock: Double = 2.5
    static let lamp: Double = 2
    static let spines: Double = 1
}

extension View {
    /// The room's one pointer cue (§8): a link cursor over things that do
    /// something — `pointerStyle(.link)` on macOS 15+, the pointing hand
    /// pushed and popped on macOS 14. Inert props never get it (R-Z2).
    @ViewBuilder
    func roomLinkCursor() -> some View {
        if #available(macOS 15, *) {
            self.pointerStyle(.link)
        } else {
            self.modifier(PushedLinkCursor())
        }
    }
}

/// The macOS 14 fallback for `roomLinkCursor`. NSCursor's stack is global, so
/// a push and a pop must pair exactly (Task 6 review r1): the plan's bare
/// `onHover` push/pop popped a cursor it never pushed on an unmatched
/// hover-out, and never popped at all when the view was torn down while
/// hovered (a mood change swapping the hotspot out under the pointer), which
/// left the whole app on a pointing hand. `pushed` makes each side idempotent,
/// and `onDisappear` closes the pair a teardown would have left open.
private struct PushedLinkCursor: ViewModifier {
    @State private var pushed = false

    func body(content: Content) -> some View {
        content
            .onHover { inside in inside ? push() : pop() }
            .onDisappear { pop() }
    }

    private func push() {
        guard !pushed else { return }
        NSCursor.pointingHand.push()
        pushed = true
    }

    private func pop() {
        guard pushed else { return }
        NSCursor.pop()
        pushed = false
    }
}

/// The study room (G125 v3 → Track Z v4): the inert art (`DeskSceneView`),
/// the worm on its lattice, the real pile, and — separately — the hotspot
/// layer derived from the same pure layout (R-Z8). The ONE reader of the
/// continuous pointer under `Views/Sleep/` (`SleepNumbersLintTests`); it
/// writes the model and reads nothing from it, so its own body never
/// re-evaluates for a moving pointer.
struct StudyRoom: View {
    let page: SleepPageModel
    let statusLine: SentenceLine
    let answers: [SentenceLine]
    let room: RoomModel
    /// Track Z Z6 — what a spine's popover lists, and where its "+N more" and
    /// the remainder spine go (Details › What's waiting).
    let episodes: [EpisodeQueueItem]
    let onOpenDetails: (DetailsSection) -> Void
    /// Task 8 — follows T7's link; `nil` while no completion link lives, so
    /// the worm offers the named action only when it has somewhere to go.
    var onWhatChanged: (() -> Void)? = nil
    /// Track Z Z9 (I15) — false while the page is stale (R-A12): a drop is
    /// declined in the worm's words and nothing is sent (Z-B9).
    var reachable: Bool = true

    @Environment(IntakeRouter.self) private var intake
    @Environment(AppRouter.self) private var appRouter: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePaused) private var hostPaused
    @AppStorage(SceneryMode.defaultsKey) private var sceneryRaw = SceneryMode.localWeather.rawValue
    @AppStorage(ManualScenery.timeKey) private var timeRaw = "day"
    @AppStorage(ManualScenery.baseKey) private var baseRaw = "sunny"
    @State private var windowVisible = false

    var body: some View {
        let scene = deskSceneLayout()
        let spots = deskHotspots(scene)
        let mode = SceneryMode.stored(sceneryRaw)
        let zoneID = SceneStore.shared.timeZoneIdentifier
        let onScreen = windowVisible && !hostPaused && appRouter?.settingsOpen != true
        let scenery = Scenery.resolve(mode: mode, clock: SceneStore.shared.phase,
                                      forecast: LocalWeatherReader.shared.base(for: zoneID), mood: page.mood,
                                      manual: ManualScenery(timeRaw: timeRaw, baseRaw: baseRaw))
        ZStack(alignment: .bottomLeading) {
            // The lamp still means schedule; the worm still means Sleep. Environment is independent.
            SceneryRoomArt(lampLit: page.lampLit, scenery: scenery, cell: scene.cell, includesClock: false) {
                WormStage(mood: page.mood, room: room, cell: scene.cell,
                          lighting: scenery.lighting, lampLit: page.lampLit)
            }
            if let clock = scene.layers.first(where: { $0.prop == .clock }) {
                RoomClock(lighting: scenery.lighting, cell: scene.cell, onScreen: onScreen)
                    .offset(x: CGFloat(clock.cellX) * scene.cell, y: -CGFloat(clock.cellY) * scene.cell)
            }
            // The REAL pile, in the column the layout reserves for it —
            // never a painted stack (P10).
            BookPileView(books: page.books, rows: page.rows, episodes: episodes, room: room,
                         onOpenDetails: onOpenDetails, layout: scene)
                .frame(width: scene.pileFrame.width, height: scene.pileFrame.height, alignment: .bottomLeading)
                .offset(x: scene.pileFrame.minX, y: -scene.pileFrame.minY)
            if let lamp = spots[.lamp] {
                // I8/I9 — the lamp opens the schedule; the art never previews
                // (P11): it relights only when `sleepVM.schedule` changes.
                Button { room.lampPopover = .lamp } label: { Color.clear.contentShape(Rectangle()) }
                    .buttonStyle(.cicadaPlain)
                    .frame(width: lamp.width, height: lamp.height)
                    .roomLinkCursor()
                    .help(page.lampLit ? "\(page.scheduleText) · \(page.nextRunText)" : Copy.lampOffExplainer)
                    .accessibilityLabel(lampAccessibilityLabel(lampLit: page.lampLit, scheduleText: page.scheduleText,
                                                               nextRunText: page.nextRunText))
                    .accessibilityHint(Copy.lampHint)
                    .accessibilitySortPriority(RoomA11yOrder.lamp)
                    .popover(isPresented: Binding(get: { room.lampPopover == .lamp },
                                                  set: { if !$0 { room.lampPopover = nil } }),
                             arrowEdge: .top) { LampPopover(page: page) }
                    .offset(x: lamp.minX, y: -lamp.minY)
            }
            if let window = spots[.window] {
                // I11 — the window opens its legend: the weather's text twin.
                Button { room.legendShown = true } label: { Color.clear.contentShape(Rectangle()) }
                    .buttonStyle(.cicadaPlain)
                    .frame(width: window.width, height: window.height)
                    .roomLinkCursor()
                    .help(scenery.text)
                    .accessibilityLabel("Window, \(scenery.text)")
                    .accessibilityHint(Copy.windowHint)
                    .accessibilitySortPriority(RoomA11yOrder.window)
                    .popover(isPresented: Binding(get: { room.legendShown }, set: { room.legendShown = $0 }),
                             arrowEdge: .top) { WindowLegend(current: scenery) }
                    .offset(x: window.minX, y: -window.minY)
            }
            if let worm = spots[.worm] {
                WormHotspot(mood: page.mood, bracket: sleepDebtBracketText(page.mood, debt: page.debt),
                            help: statusLine.spoken, answers: answers, room: room,
                            whatChanged: onWhatChanged, onFeed: { feed(IntakePicker.choose()) })
                    .frame(width: worm.width, height: worm.height)
                    .offset(x: worm.minX, y: -worm.minY)
            }
        }
        .frame(width: scene.size.width, height: scene.size.height, alignment: .bottomLeading)
        // I12 — the drop cue is chrome (a stroke), and a leaf: a drag redraws it alone.
        .overlay { DropOutline(room: room) }
        // The whole room is the hover surface (Task 6 review r1). Hover only
        // reaches the parts of a view that hit-test, and the art and the worm
        // are `.allowsHitTesting(false)` (and a `.frame` adds no hit area), so
        // without this the pointer registered only over the hotspot and the
        // pile: the gaze never turned left over the lamp or the window (I1),
        // and the dwell counted a pointer resting there as gone. Children with
        // their own gestures sit above this shape and keep their clicks — the
        // same pattern as the sidebar rows.
        .contentShape(Rectangle())
        .onContinuousHover(coordinateSpace: .local) { phase in
            switch phase {
            case .active(let location):
                room.pointer(at: location, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            case .ended:
                room.pointer(at: nil, scene: scene, spots: spots, state: page.mood, reduceMotion: reduceMotion)
            }
        }
        // Track Z Z9 (§7.4) — the whole room is the drop target; the one intake decides.
        .onDrop(of: [.fileURL], delegate: RoomDropDelegate(room: room, intake: intake, scene: scene, spots: spots,
                                                           mood: page.mood, onDrop: { feed($0) }))
        // Z-B8 — a claim never outlives the room: a page torn down mid-drag
        // (a tab switch) would otherwise keep the window's veil hidden.
        .onDisappear { intake.releaseDrop(.sleepRoom) }
        .background(WindowVisibilityReader { windowVisible = $0 })
        .task(id: WeatherWatchKey(onScreen: onScreen, mode: mode, zone: zoneID)) {
            await LocalWeatherReader.shared.watch(onScreen: onScreen, mode: mode,
                                                   zone: TimeZone(identifier: zoneID) ?? .autoupdatingCurrent)
        }
        .onChange(of: page.mood.caseName) { old, _ in
            room.moodChanged(from: old, to: page.mood, reduceMotion: reduceMotion)
        }
        // The art identity changes on a lighting/sky swap; the beat's lifetime belongs to the stable room.
        .task(id: room.reaction?.id) { await room.settleReaction() }
        .task(id: room.transition?.id) { await room.settleTransition() }
        .accessibilityElement(children: .contain)
    }

    /// I15 / I16 — one path for a drop and for the picker (Z-B17): the router
    /// decides (its guard is every door's, Z-B5), and the room tells what it
    /// decided — a beat the matrix allows, a line, an announcement (§11: the
    /// person caused it).
    private func feed(_ urls: [URL]) {
        // A drop whose providers held no file URL (or a cancelled picker)
        // still ends the drag, so the worm never stays armed.
        guard !urls.isEmpty else { return room.dragEnded() }
        let result = roomFeedResult(reachable: reachable) { intake.accept(urls: urls, from: .sleepRoom) }
        room.fed(result, state: page.mood, reduceMotion: reduceMotion)
        if let phase = RoomModel.feedPhase(drag: nil, result: result, intakePhase: intake.phase) {
            AccessibilityNotification.Announcement(feedLine(phase, asleep: feedIsAsleep(page.mood)).spoken).post()
        }
    }
}

/// I12 — the dashed inset outline while a file is over the room: chrome, not
/// art (a SwiftUI stroke, never pixels in the room), `textPrimary` under
/// Increase Contrast (§11), instant under Reduce Motion.
private struct DropOutline: View {
    let room: RoomModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
            .strokeBorder(contrast == .increased ? CicadaTheme.textPrimary : CicadaTheme.accent,
                          style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
            .opacity(room.drag == nil ? 0 : 1)
            .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: room.drag == nil)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}

/// The worm and nothing else — the one leaf that reads the pointer's gaze
/// and the beat (§10), so a moving pointer redraws only this. Inert: the
/// hotspot above it takes the clicks.
struct WormStage: View {
    let mood: BookwormState
    let room: RoomModel
    let cell: CGFloat
    var lighting: RoomLighting = .day
    var lampLit: Bool = false

    var body: some View {
        BookwormView(state: mood, latticeCell: cell, caption: nil,
                     pose: Self.pose(drag: room.drag, pointerInRoom: room.pointerInRoom, gaze: room.gaze),
                     reaction: room.reaction, transition: room.transition, lighting: lighting, lampLit: lampLit)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    /// A drag outranks the pointer (§6.1): the armed pose is the drop cue.
    /// Pure; tested.
    static func pose(drag: RoomDrag?, pointerInRoom: Bool, gaze: Gaze) -> BookwormPose {
        drag?.pose ?? (pointerInRoom ? .attentive(gaze) : .idle)
    }
}

/// The worm's hotspot (I2, I3; §11): click, Space or Return pokes; Esc
/// dismisses while it has focus (Z-P15); VoiceOver's default action pokes and
/// "What are you doing?" reads every rung at once. The bracket line (P8)
/// lives on as this element's VALUE — the scene group used to carry it as a
/// label, and the worm is where a listener now meets it.
struct WormHotspot: View {
    let mood: BookwormState
    let bracket: String
    let help: String
    let answers: [SentenceLine]
    let room: RoomModel
    /// §11 — while T7's link lives, VoiceOver reaches it from the worm too.
    var whatChanged: (() -> Void)? = nil
    /// Track Z Z9 (I16) — *Feed a file…*: the intake's own picker, for anyone
    /// without a file to drag (the keyboard, VoiceOver, a trackpad).
    var onFeed: (() -> Void)? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .onTapGesture { poke() }
            .focusable()
            .onKeyPress(.space) { poke(); return .handled }
            .onKeyPress(.return) { poke(); return .handled }
            .onKeyPress(.escape) {
                guard room.answerIndex != nil || room.feedResult?.isTerminal == true else { return .ignored }
                room.dismissSlot()
                // I4 — Esc is the one dismissal the person caused, so it is
                // the one that announces: the status sentence is back.
                AccessibilityNotification.Announcement(help).post()
                return .handled
            }
            .roomLinkCursor()
            .help(help)
            .contextMenu {
                Button(Copy.wormWhatAreYouDoing) { announceAll() }
                // I16 — the keyboard's and the trackpad's way to feed: the intake's own picker.
                if let onFeed { Button(Copy.feedAFile, action: onFeed) }
            }
            .accessibilityElement()
            .accessibilityLabel("Bookworm, \(mood.title)")
            .accessibilityValue(bracket)
            .accessibilityHint(Copy.wormHint)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { poke() }
            .accessibilityAction(named: Copy.wormWhatAreYouDoing) { announceAll() }
            .accessibilityActions {
                if let onFeed { Button(Copy.feedAFile, action: onFeed) }   // I16, §11
                if let whatChanged {
                    Button(Copy.whatChanged, action: whatChanged)   // §11 — while T7's link lives
                }
            }
            .accessibilitySortPriority(RoomA11yOrder.worm)
    }

    /// Announcements fire only for what the person caused (§11).
    private func poke() {
        if let index = room.poke(answerCount: answers.count, state: mood, reduceMotion: reduceMotion),
           answers.indices.contains(index) {
            AccessibilityNotification.Announcement(answers[index].spoken).post()
        }
    }

    private func announceAll() {
        AccessibilityNotification.Announcement(answers.map(\.spoken).joined(separator: " ")).post()
    }
}
