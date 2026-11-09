import SwiftUI

/// Home — the front door at ⌘1 (G108, ruled 2026-09-23 as spec decision 12;
/// design §6), drawn in Direction D (DS-3b, R-HS2; the painted band retired
/// 2026-10-16): the headline, the palette's own field (`FindPanelBody` in
/// `.page` placement, R-IB6), then Needs you / Today / Last read as labelled
/// blocks — every number once, each a link to the page
/// that owns it (R-IB9). There is no Consolidate here: one Consolidate, on the
/// Sleep page (G125 R10, R-HS3). The first keystroke replaces the blocks with
/// results (design H2); Esc clears the field and brings them back.
///
/// Rebuilt on every tab switch, unlike the graph (R-IB3): a SwiftUI tree is
/// cheap where a `WKWebView` re-layout is not (G109). What must survive — the
/// text left in the field — lives in `HomeSearch`, held by the app.
///
/// Home adds no drop target (R-IB8): the window-level drop already covers it
/// and raises the one intake.
///
/// Owner ruling 2026-10-14, "Graduate + Needs you first": the blocks follow the person's state (`HomeArrangement`).
/// In the first week Getting started leads; once the person has chats in memory it graduates to one line at the foot,
/// and Needs you leads. *Make it yours* and the tour offer never sit above Needs you.
struct HomeView: View {
    let open: (FindDestination) -> Void
    @Binding var selectedTab: AppTab

    @Environment(HomeSearch.self) private var search
    /// Getting started's record lives in defaults (not observable); the
    /// runner's revision is what makes a record write re-render Home.
    @Environment(SetupRunner.self) private var runner
    @Environment(Store.self) private var store
    @Environment(IntakeRouter.self) private var intake
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(TourController.self) private var tour
    @AppStorage(AppearanceTipPolicy.armedKey) private var tipArmed = false
    @AppStorage(AppearanceTipPolicy.dismissedKey) private var tipDismissed = false
    @AppStorage(AppearanceTipPolicy.seenKey) private var tipSeen = false
    /// Review #1 — the vendor whose drawn export walkthrough is open over Home.
    @State private var seeHow: ChatVendor?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(InboxViewModel.self) private var inboxVM
    /// Say it once — bumps when Home is clicked again in the rail, so the page scrolls back to its headline.
    @State private var toTop = 0
    private static let topAnchor = "home.top"

    var body: some View {
        let showsResults = FindPanelBody.showsBody(placement: .page, query: search.model.query,
                                                   mode: search.model.mode)
        // One clock per evaluation, so every section agrees on which UTC day "today" is.
        let today = Date()
        let _ = runner.checklistRevision
        // Owner 2026-10-14 — the person's state orders the page: setup leads only while it is whole and the person has
        // no chats in memory yet (`HomeArrangement`, `HomeSetup.hasChatsInMemory`).
        let setupRecord = GettingStartedState.load(bank: store.bank)
        let setupVisible = GettingStartedProgress.visible(record: setupRecord) || runner.sawDoneThisSession
        let graduated = HomeSetup.hasChatsInMemory(store.sourcesOverview.value) == true
        let arrangement = HomeArrangement.of(setupVisible: setupVisible, graduated: graduated)
        // While the whole card (and so its read row) shows — the first week, or a graduated card its viewer opened —
        // TODAY omits its own waiting clause (`HomeLayout`, every number once).
        let gettingStartedVisible = setupVisible && (!graduated || setupRecord?.expanded == true)
        let empty = emptiness(today: today, gettingStartedVisible: gettingStartedVisible)
        // F-09 (R-HO15) — the first-time "Make it yours", never beside search results, one session only.
        let tipShown = AppearanceTipPolicy.visible(armed: tipArmed, dismissed: tipDismissed, seenBefore: tipSeen,
                                                   shownThisSession: AppearanceTipPolicy.shownThisSession)
            && !showsResults
        Group {
        if let session = search.catchup, session.bank == store.bank {
            // Ruling 48 (8) — Catch me up opens in place on Home as a chat; Esc, × or Home's cell leave it.
            CatchupView(session: session, onClose: { closeCatchup() }, openPage: { open(.entity(id: $0)) },
                        openQuestion: { id in
                            router?.pendingInboxItem = id
                            selectedTab = .inbox
                        })
        } else {
        GeometryReader { geo in
            VStack(spacing: 0) {
                // Owner 2026-10-06 — one scroll view carries the headline, the field and the blocks, so a scrolled card
                // leaves under the window's edge whole, never cut flush under the field (the field used to sit above the
                // blocks' own scroll view). The field keeps one place in the tree in both states, so the first keystroke
                // never drops its focus: with results the page pins to the viewport and the results fill what is left.
                // The swap is instant — typing and Esc drive it, and a keyboard action never animates (DR-60).
                GeometryReader { viewport in
                    ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: 0) {
                            // R-HS2 — the headline is the row under the band, on the window (DR-50), in the room pages'
                            // title (DR-17): one line, the mock's words.
                            // ROR-118 round 3 — the worm greets over the headline: the page's one picture, small, on the
                            // window and never behind a word or a figure (DR-13), at rest or at its mood.
                            HomeGreeter(state: mascotState)
                                .id(Self.topAnchor)
                                .padding(.top, CicadaTheme.scaled(HomeLayout.headlineTop(viewportHeight: viewport.size.height)))
                                .padding(.bottom, CicadaTheme.scaled(HomeLayout.greeterGap))
                            PageTitle(Copy.homeHeadline, fontSize: HomeLayout.headlineSize)
                                .multilineTextAlignment(.center)
                                .accessibilityAddTraits(.isHeader)
                                .padding(.bottom, CicadaTheme.scaled(HomeLayout.headlineBottom))
                            fieldColumn(showsResults: showsResults)
                                .frame(maxWidth: CicadaTheme.scaled(HomeLayout.fieldWidth))
                            if !showsResults {
                                // Between the field and the end of the page, and only while the blocks show (R-IB6): the
                                // first keystroke replaces them too.
                                VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.blockGap)) {
                                    HomeExportWaitStrip()   // ROR-126: the worm waiting on an export, per provider
                                    ForEach(Array(arrangement.order.enumerated()), id: \.element) { index, id in
                                        // ROR-118 — Today and Last read are one quiet group when they sit together.
                                        block(id, today: today, gettingStartedVisible: gettingStartedVisible,
                                              graduated: graduated, empty: empty, tipShown: tipShown,
                                              joinsToday: id == .lastRead && index > 0 && arrangement.order[index - 1] == .today,
                                              takesLastRead: id == .today && index + 1 < arrangement.order.count
                                                  && arrangement.order[index + 1] == .lastRead)
                                    }
                                }
                                .tourAnchor(.home)
                                .frame(maxWidth: CicadaTheme.scaled(HomeLayout.fieldWidth))   // ROR-118 r2 — one column: the field's edges
                                .padding(.top, CicadaTheme.scaled(HomeLayout.fieldToFirstBlock))
                                .padding(.bottom, CicadaTheme.scaled(HomeLayout.bottomPadding))
                            }
                        }
                        .padding(.horizontal, CicadaTheme.spacingGutter)
                        .frame(maxWidth: .infinity, alignment: .top)
                        .frame(height: showsResults ? viewport.size.height : nil, alignment: .top)
                    }
                    .modifier(HomePageScroll(pinned: showsResults))
                    .onChange(of: toTop) { _, _ in Instant.run { proxy.scrollTo(Self.topAnchor, anchor: .top) } }
                    }
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        }
        }
        .background(CicadaTheme.bgBase)
        // Review #1 — onboarding's drawn walkthrough, over Home, from a vendor row's "See how ›".
        .overlay {
            if let vendor = seeHow {
                HomeWalkthroughLayer(vendor: vendor, onClose: { seeHow = nil }, onHaveFile: {
                    // CIC8 — straight to the intake's picker (it opens in Downloads); what is picked previews over Home.
                    seeHow = nil
                    let urls = IntakePicker.choose()
                    if !urls.isEmpty { intake.accept(urls: urls, from: .home) }
                })
            }
        }
        .onAppear { tour.adoptOffer() }
        // Say it once — Home clicked again in the rail: the field empties (Find, not Ask), the walkthrough closes and
        // the page is back at its headline.
        .onRailReselect(.home, router: router) { popToRoot() }
        // Sleep history is not a Store domain and is not disk-cached (design
        // §6.3): fetch it on every arrival, and again whenever the status's last
        // read moves (a read that finished while Home is up, a status that only
        // arrived once the backend came up after a failed first fetch), so LAST
        // READ says "Looking up…" only until it lands, never a stale read. A
        // bank switch rereads it in `SleepViewModel.bankChanged()`. A load whose
        // schedule fetch failed is retried here too, or Getting started's
        // schedule question would never be asked (R-IB20).
        .task(id: store.status.value?.lastSleepAt) { await sleepVM.refreshForHome() }
    }

    /// The worm's mood is the menu bar's, from the same status; the waiting count is already a figure on this page, so
    /// the badge that carries it there never draws here — a worm reading a book says the same thing without a number.
    private var mascotState: BookwormState {
        let state = store.status.value.map { deriveBookwormState($0, justFinishedAt: nil) } ?? .awake
        if case .curious = state { return .reading }
        return state
    }

    private func popToRoot() {
        guard let router else { return }
        router.popToRoot(reduceMotion: reduceMotion) {
            // Mode first: leaving Ask puts its question back in the field (`setMode`), so the clear comes after.
            search.model.setMode(.find)
            search.model.setQuery("")
            seeHow = nil
            search.catchup = nil
        }
        toTop &+= 1
    }

    // MARK: Catch me up (ruling 48 (8))

    private func startCatchup(_ queue: [String], leadsWithContext: Bool = false) {
        search.catchup = CatchupSession.live(queue: queue, store: store, inbox: inboxVM, leadsWithContext: leadsWithContext)
    }

    private func closeCatchup() {
        search.catchup = nil
    }

    // MARK: The blocks

    /// One block of the column, by id — `HomeArrangement` owns the order, this owns nothing but the mapping.
    @ViewBuilder
    private func block(_ id: HomeBlockID, today: Date, gettingStartedVisible: Bool, graduated: Bool,
                       empty: HomeEmptiness, tipShown: Bool, joinsToday: Bool, takesLastRead: Bool) -> some View {
        let mode = empty.mode(setupCardShown: gettingStartedVisible)
        // ROR-118 round 4 — Last read under Today is the status line's last segment, one line, never a second block.
        let oneLine = mode == .blocks && !empty.todayEmpty && !empty.lastReadNever
        switch id {
        case .setup:
            GettingStartedCard(selectedTab: $selectedTab, seeHow: $seeHow, graduated: graduated)
        case .today:
            switch mode {
            case .blocks:
                TodaySection(today: today, gettingStartedVisible: gettingStartedVisible, empty: empty.todayEmpty,
                             includesLastRead: takesLastRead && oneLine, selectedTab: $selectedTab)
            case .one:
                HomeEmptyBlock()   // review #8 — one block says it once, where Today would be
            case .hidden:
                EmptyView()
            }
        case .needsYou:
            if mode == .blocks {
                NeedsYouSection(empty: empty.needsYouEmpty, selectedTab: $selectedTab,
                                answerIsPrimary: !gettingStartedVisible,
                                openPage: { open(.entity(id: $0)) },
                                startCatchup: { startCatchup($0) },
                                startAnswer: { startCatchup($0, leadsWithContext: true) })
            }
        case .readingSites:
            ReadingSitesSection()
        case .lastRead:
            if mode == .blocks && !(joinsToday && oneLine) {
                LastReadSection(empty: empty.lastReadNever, selectedTab: $selectedTab)
            }
        case .tour:
            // Seam 3 — onboarding's "Open Cicada" asked for the tour's offer; Home asks once.
            if tour.offerPending { TourOfferCard() }
        case .tip:
            if tipShown { AppearanceTip() }
        }
    }

    /// Review #8 — the three blocks' emptiness, from the same figures they render. Unknown is never empty (R-A14).
    private func emptiness(today: Date, gettingStartedVisible: Bool) -> HomeEmptiness {
        let hasRunBefore = sleepVM.status?.debt.hasRunBefore ?? (store.status.value?.lastSleepAt != nil)
        let lastRead = HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                            failed: sleepVM.historyFailed,
                                            hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                                ?? store.status.value.map { $0.lastSleepAt != nil },
                                            lastSleepAt: store.status.value?.lastSleepAt)
        return HomeEmptiness(captured: HomeFigures.today(store.sourcesOverview.value, today: today).captured,
                             waiting: store.status.value?.episodes.unprocessed,
                             showsWaiting: HomeLayout.showsWaitingInToday(gettingStartedVisible: gettingStartedVisible,
                                                                          hasRunBefore: hasRunBefore),
                             needsYou: store.visibleInbox.count,
                             inboxLoaded: store.inbox.value != nil,
                             lastReadNever: lastRead == .never)
    }

    // MARK: The field

    /// The palette's own body in `.page` placement (R-IB6), unchanged, in D's grouped-block
    /// material: `bgFocus`, `cornerRadius`, a resting ring (`glassCard()` — the mock's 10 pt block).
    @ViewBuilder
    private func fieldColumn(showsResults: Bool) -> some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            if let url = LinkPaste.url(in: search.model.query) {
                saveLinkRow(url)
            }
            FindPanelBody(model: search.model, placement: .page, open: open,
                          prompt: Copy.homeFieldPrompt, focusRequest: search.focusRequest,
                          submitOverride: {
                              guard let url = LinkPaste.url(in: search.model.query) else { return false }
                              save(url)
                              return true
                          })
                .modifier(HomeLeadField())
                .frame(maxHeight: showsResults ? .infinity : nil)
        }
        .frame(maxHeight: showsResults ? .infinity : nil, alignment: .top)
    }

    /// R-IB7 — a paste that IS one link offers to save it; ⏎ does the same.
    private func saveLinkRow(_ url: URL) -> some View {
        Button { save(url) } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                // DR-5 has no "decorative glyph" use: the glyph is neutral.
                Image(systemName: "link")
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(Copy.homeSaveLinkRow(LinkPaste.host(url)))
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                KeyHint("⏎")   // DR-49 — the key that acts, shown where it acts
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .glassCard()
        }
        .buttonStyle(.cicadaPlain)
    }

    /// Saves through the same `/sources/save` the `+` sheet's *Paste a link*
    /// tile uses, then refreshes only the two domains a saved link moves.
    private func save(_ url: URL) {
        let host = LinkPaste.host(url)
        Task {
            do {
                _ = try await APIClient.shared.saveURL(url.absoluteString)
                store.toast = Copy.homeLinkSaved(host)
                search.model.setQuery("")
                await store.refresh([.sources, .sourcesOverview])
            } catch {
                store.toast = AddSourceSheet.friendlyError(error)
            }
        }
    }
}

/// ROR-118 round 2 (DR-9, DR-10) — the field is the page's one raised surface: a step lighter than the cards under it
/// in dark (`bgOption`; light cards are white already) and the input ring (`.input`), never a shadow; the cards below stay on `surface` with the resting ring,
/// so depth says what leads.
struct HomeLeadField: ViewModifier {
    func body(content: Content) -> some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadius)
        content
            .background(shape.fill(CicadaTheme.mode == .dark ? CicadaTheme.bgButton : CicadaTheme.bgFocus))
            .clipShape(shape)
            .ringed(.input, in: shape)
    }
}

/// Home's page scroll (owner 2026-10-06). With results showing the page is pinned to the viewport by its height, so the
/// outer scroll has nothing to move and only stops rubber-banding; it never disables scrolling, because
/// `scrollDisabled` reaches every scroll view inside — the results' and Ask's own — and would freeze them.
struct HomePageScroll: ViewModifier {
    let pinned: Bool

    func body(content: Content) -> some View {
        content
            .scrollBounceBehavior(pinned ? .basedOnSize : .automatic, axes: .vertical)
            .scrollIndicators(.automatic)
            .softTopScrollEdge()
    }
}

/// ROR-118 rounds 3 and 4 (DR-13; DESIGN_RULES §9 2026-11-06) — Home's one picture: the study room's worm over the
/// headline, the room's pixel art on the window's own ground, drawn at a whole 3 points per art pixel and cropped to the
/// pixels it ever draws. It carries no words and no number, never sits behind either, and its mood and Reduce Motion are
/// the sprite clock's.
struct HomeGreeter: View {
    let state: BookwormState

    var body: some View {
        // A whole number of points per art pixel at any zoom, like the Sleep page's room (never fractional, so a resize
        // never blurs a pixel).
        let cell = max(1, (HomeLayout.greeterCell * CicadaTheme.uiScale).rounded())
        let ink = HomeLayout.greeterInk
        BookwormView(state: state, latticeCell: cell)
            .offset(x: -ink.minX * cell, y: -ink.minY * cell)
            .frame(width: ink.width * cell, height: ink.height * cell, alignment: .topLeading)
            .clipped()
            .accessibilityHidden(true)
    }
}
