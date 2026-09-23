import SwiftUI

/// VoiceOver's order through the default view (Track Z §11): the sentence,
/// the worm, the window, the lamp, the spines (largest first), the control,
/// the whisper line, then Details. One table, read by every element that
/// sets a priority, so the order can be reviewed in one place.
///
/// **Two levels, because a sort priority only orders siblings inside one
/// accessibility container.** The room card is a `.contain` container
/// (sentence → room → control → whisper; the strip, when shown, keeps the
/// default 0 and reads last). The room is its own `.contain` container inside
/// it (worm → window → lamp → the pile's container, whose spines order
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

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let scene = deskSceneLayout(pointSize: SleepView.wormPointSize)
        let spots = deskHotspots(scene)
        ZStack(alignment: .bottomLeading) {
            // R-A3: lit exactly when Sleep is scheduled — the lamp and the
            // whisper line read the same field, so the art never disagrees
            // with the words.
            DeskSceneView(pointSize: SleepView.wormPointSize, lampLit: page.lampLit)
            WormStage(mood: page.mood, room: room, pointSize: SleepView.wormPointSize)
                .offset(x: scene.wormOrigin.x, y: -scene.wormOrigin.y)   // R-Z4: the lattice placement, whole cells
            // The REAL pile, in the column the layout reserves for it —
            // never a painted stack (P10).
            BookPileView(books: page.books, rows: page.rows, episodes: episodes, room: room,
                         onOpenDetails: onOpenDetails)
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
            if let worm = spots[.worm] {
                WormHotspot(mood: page.mood, bracket: sleepDebtBracketText(page.mood, debt: page.debt),
                            help: statusLine.spoken, answers: answers, room: room,
                            whatChanged: onWhatChanged)
                    .frame(width: worm.width, height: worm.height)
                    .offset(x: worm.minX, y: -worm.minY)
            }
        }
        .frame(width: scene.size.width, height: scene.size.height, alignment: .bottomLeading)
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
        .accessibilityElement(children: .contain)
    }
}

/// The worm and nothing else — the one leaf that reads the pointer's gaze
/// and the beat (§10), so a moving pointer redraws only this. Inert: the
/// hotspot above it takes the clicks.
struct WormStage: View {
    let mood: BookwormState
    let room: RoomModel
    let pointSize: CGFloat

    var body: some View {
        BookwormView(state: mood, pointSize: pointSize, caption: nil,
                     pose: room.pointerInRoom ? .attentive(room.gaze) : .idle,
                     reaction: room.reaction)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            .task(id: room.reaction?.id) { await room.settleReaction() }
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

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .onTapGesture { poke() }
            .focusable()
            .onKeyPress(.space) { poke(); return .handled }
            .onKeyPress(.return) { poke(); return .handled }
            .onKeyPress(.escape) {
                guard room.answerIndex != nil else { return .ignored }
                room.dismissAnswers()
                // I4 — Esc is the one dismissal the person caused, so it is
                // the one that announces: the status sentence is back.
                AccessibilityNotification.Announcement(help).post()
                return .handled
            }
            .roomLinkCursor()
            .help(help)
            .contextMenu { Button(Copy.wormWhatAreYouDoing) { announceAll() } }
            .accessibilityElement()
            .accessibilityLabel("Bookworm, \(mood.title)")
            .accessibilityValue(bracket)
            .accessibilityHint(Copy.wormHint)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { poke() }
            .accessibilityAction(named: Copy.wormWhatAreYouDoing) { announceAll() }
            .accessibilityActions {
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
