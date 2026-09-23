import SwiftUI

/// Home — the front door at ⌘1 (G108, ruled 2026-09-23 as spec decision 12;
/// design §6). Search first: the palette's own field (`FindPanelBody` in
/// `.page` placement, R-IB6), then Today / Needs you / Last read — every number
/// once, each a link to the page that owns it (R-IB9). The first keystroke
/// replaces the cards with results (design H2); Esc clears the field and
/// brings them back.
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
    /// Task 3 fills this from the Getting started record; while its read row
    /// shows, TODAY omits its own waiting clause (`HomeLayout`, every number once).
    var gettingStartedVisible = false

    @Environment(HomeSearch.self) private var search
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let showsResults = FindPanelBody.showsBody(placement: .page, query: search.model.query,
                                                   mode: search.model.mode)
        // One clock per evaluation, so every section agrees on which UTC day "today" is.
        let today = Date()
        VStack(spacing: 0) {
            band
            VStack(spacing: CicadaTheme.spacingLG) {
                fieldColumn(showsResults: showsResults)
                if !showsResults {
                    ScrollView {
                        HomeSections(today: today, gettingStartedVisible: gettingStartedVisible,
                                     selectedTab: $selectedTab)
                            .padding(.bottom, CicadaTheme.spacingXL)
                    }
                    .scrollIndicators(.automatic)
                    .transition(.opacity)
                }
            }
            .frame(maxWidth: CicadaTheme.scaled(720), maxHeight: .infinity, alignment: .top)
            .padding(.horizontal, CicadaTheme.spacingXL)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .animation(CicadaMotion.morph(reduceMotion: reduceMotion), value: showsResults)
        }
        .background(CicadaTheme.background)
        // Sleep history is not disk-cached (design §6.3): fetch it on every
        // arrival so LAST READ is "—" only until it lands, never a stale read.
        .task {
            if sleepVM.status == nil { await sleepVM.load() } else { await sleepVM.loadHistory() }
        }
    }

    // MARK: The band

    /// A procedural sky and one cloud (`HomeSkyBand`, R-IB10); the headline sits
    /// on the gradient — never on paint — inside `HomeBandLayout.headlineFrame`,
    /// the rectangle the layout test proves the drifting cloud never crosses.
    private var band: some View {
        ZStack {
            HomeSkyBand()
            GeometryReader { geo in
                let frame = HomeBandLayout.headlineFrame(width: geo.size.width, scale: CicadaTheme.uiScale)
                VStack(spacing: 0) {
                    Text(Copy.homeHeadline)
                        .font(CicadaTheme.displayFont(size: HomeBandLayout.headlineSize))
                    Text(Copy.homeHeadlineItalic)
                        .font(CicadaTheme.displayFont(size: HomeBandLayout.headlineSize, italic: true))
                }
                .foregroundStyle(CicadaTheme.textPrimary)
                .multilineTextAlignment(.center)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
                .frame(width: frame.width, height: frame.height)
                .position(x: frame.midX, y: frame.midY)
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(.isHeader)
            }
        }
        .frame(height: CicadaTheme.scaled(HomeBandLayout.bandHeight))
    }

    // MARK: The field

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
                .glassCard(cornerRadius: CicadaTheme.radiusLarge)   // a standard material: content (R-M5)
                .frame(maxHeight: showsResults ? .infinity : nil)
        }
        .padding(.top, CicadaTheme.spacingLG)
        .frame(maxHeight: showsResults ? .infinity : nil, alignment: .top)
    }

    /// R-IB7 — a paste that IS one link offers to save it; ⏎ does the same.
    private func saveLinkRow(_ url: URL) -> some View {
        Button { save(url) } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "link")
                    .foregroundStyle(CicadaTheme.accent)
                    .accessibilityHidden(true)
                Text(Copy.homeSaveLinkRow(LinkPaste.host(url)))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(verbatim: "⏎")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
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
