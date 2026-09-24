import SwiftUI

/// Home — the front door at ⌘1 (G108, ruled 2026-09-23 as spec decision 12;
/// design §6), drawn in Direction D as the approved D-Home mock (DS-3b, R-HS2):
/// the painted band, the headline on the window under it, the palette's own
/// field (`FindPanelBody` in `.page` placement, R-IB6), then Today / Needs you /
/// Last read as labelled blocks — every number once, each a link to the page
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
struct HomeView: View {
    let open: (FindDestination) -> Void
    @Binding var selectedTab: AppTab

    @Environment(HomeSearch.self) private var search
    /// Getting started's record lives in defaults (not observable); the
    /// runner's revision is what makes a record write re-render Home.
    @Environment(SetupRunner.self) private var runner
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let showsResults = FindPanelBody.showsBody(placement: .page, query: search.model.query,
                                                   mode: search.model.mode)
        // One clock per evaluation, so every section agrees on which UTC day "today" is.
        let today = Date()
        let _ = runner.checklistRevision
        // While the card's read row shows, TODAY omits its own waiting clause
        // (`HomeLayout`, every number once).
        let gettingStartedVisible = GettingStartedProgress.visible(record: GettingStartedState.load(bank: store.bank))
            || runner.sawDoneThisSession
        GeometryReader { geo in
            VStack(spacing: 0) {
                // DR-13 — paint only: no word, no number and nothing over it (`HomeBandLayoutTests`).
                HomeHeroBand()
                    .frame(height: CicadaTheme.scaled(HomeBandLayout.bandHeight))
                VStack(spacing: 0) {
                    // R-HS2 — the headline is the row under the band, on the window (DR-50), in the
                    // room pages' title (DR-17): one line, the mock's words.
                    PageTitle(Copy.homeHeadline)
                        .multilineTextAlignment(.center)
                        .accessibilityAddTraits(.isHeader)
                        .padding(.top, CicadaTheme.scaled(HomeLayout.headlineTop))
                        .padding(.bottom, CicadaTheme.scaled(HomeLayout.headlineBottom))
                    fieldColumn(showsResults: showsResults)
                        .frame(maxWidth: CicadaTheme.scaled(HomeLayout.fieldWidth))
                    if !showsResults {
                        ScrollView {
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.blockGap)) {
                                // Between the field and TODAY, and only while the blocks show
                                // (R-IB6): the first keystroke replaces it too.
                                GettingStartedCard(selectedTab: $selectedTab)
                                HomeSections(today: today, gettingStartedVisible: gettingStartedVisible,
                                             needsYouSlots: HomeLayout.needsYouSlots(
                                                 pageWidth: geo.size.width, scale: CGFloat(CicadaTheme.uiScale)),
                                             selectedTab: $selectedTab)
                            }
                            .frame(maxWidth: CicadaTheme.scaled(HomeLayout.columnWidth))
                            .padding(.top, CicadaTheme.spacingCard)
                            .padding(.bottom, CicadaTheme.scaled(HomeLayout.bottomPadding))
                            .frame(maxWidth: .infinity)
                        }
                        .scrollIndicators(.automatic)
                        .transition(.opacity)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .animation(CicadaMotion.morph(reduceMotion: reduceMotion), value: showsResults)
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .background(CicadaTheme.bgBase)
        // Sleep history is not disk-cached (design §6.3): fetch it on every
        // arrival so LAST READ is "—" only until it lands, never a stale read.
        // A load whose schedule fetch failed is retried here too, or Getting
        // started's schedule question would never be asked (R-IB20).
        .task {
            if sleepVM.status == nil || !sleepVM.scheduleLoaded { await sleepVM.load() } else { await sleepVM.loadHistory() }
        }
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
                .glassCard()
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
