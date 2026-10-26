import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Onboarding v2, step 4 (G217, ruling 36 D6): the popular sources as a grid of `LogoTile`s to tick
/// (`SourceTiles`). A tick does exactly what that source's row does elsewhere: Calendar, Contacts and each browser
/// start through the one turn-on (`SetupRunner` → `FoundTurnOn`, R-OB2) and an untick stops them keeping up (R-OB8);
/// Messages and the accounts read through the person's browser (YouTube, X, Instagram) open the Sources page's own
/// detail over onboarding (`SourceCatalogDetail`), so its consents, chat picker and per-site switch are the page's
/// own words; chat history takes a dropped export (the window's one drop target) or the file panel, and *How to get
/// an export* opens the drawn walkthrough. Nothing is pre-ticked and nothing is read before a tick (R-OB6, R-IB12).
/// Each consent macOS asks for is named by the tile's own help line, never raised by the step. Onboarding v3
/// (2026-10-24): the tiles this Mac has data for lead and the rest fold under *More sources* (DR-39, remembered per
/// viewer, open by itself when something inside is on); a browser macOS hides opens the Full Disk Access drag helper
/// on its tick (`FoundTurnOn` → `PermissionDragHelper`); Calendar or Contacts refused in macOS's own prompt become a
/// tile that opens the exact list. DR-5, DR-9, DR-12, DR-39, DR-48, DR-52, DR-70.
struct SourcesStep: View {
    let imports: [ImportEntry]
    let snapshots: [FoundItemID: SetupRowSnapshot]
    let dropTargeted: Bool
    /// The browsers macOS hides until Full Disk Access is granted (`LocalInventory`, R-OB7).
    var needsAccess: Set<FoundItemID> = []
    /// Calendar or Contacts refused in macOS's own prompt: the tile opens the exact list (`SourceTileGroups`).
    var denied: Set<FoundItemID> = []
    let onTick: (ImportEntry, Bool) -> Void
    let onSeeHow: (ChatVendor) -> Void

    @Environment(Store.self) private var store
    @Environment(IntakeRouter.self) private var intake
    @State private var reading = ReadingAgentModel()
    @State private var opened: SourceCatalogEntry?
    /// DR-39 — each viewer's choice is remembered. A new key; nothing else reads it.
    @AppStorage("cicada.onboarding.moreSources") private var moreOpen = false

    private var tiles: [SourceTile] { SourceTiles.tiles(imports: imports) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.importTitle, subline: Copy.sourcesSubline)
            let groups = SourceTileGroups.split(tiles)
            grid(groups.lead)
            if !groups.more.isEmpty {
                let open = SourceTileGroups.moreStartsOpen(remembered: moreOpen,
                                                           anyOnInside: groups.more.contains { state(of: $0).ticked })
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    DisclosureHeader(title: Copy.sourcesMore, summary: groups.more.map(\.title).joined(separator: " · "),
                                     isOpen: open) { moreOpen = !open }
                    if open { grid(groups.more).disclosureReveal() }
                }
            }
            if let error = intake.welcomeDropError {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TextButton(title: Copy.sourcesHowToExport, inline: true, flushLeading: true) { onSeeHow(.claude) }
        }
        .task { await reading.loadSettings() }
        .sheet(item: $opened) { entry in
            SourceCatalogDetail(row: catalogRow(entry), onClose: { opened = nil })
                .environment(reading)
                .frame(width: CicadaTheme.scaled(560), height: CicadaTheme.scaled(SourcesStepLayout.sheetHeight))
                .background(CicadaTheme.bgBase)
        }
    }

    private func grid(_ tiles: [SourceTile]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(OnboardingLayout.sourceTile)),
                                     spacing: CicadaTheme.spacingSM)],
                  alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(tiles) { tile in tileView(tile) }
        }
    }

    // MARK: A tile

    private func tileView(_ tile: SourceTile) -> some View {
        let state = state(of: tile)
        return Button { press(tile) } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(alignment: .top) {
                    if tile.kind == .chats {
                        // Any vendor's export lands here: a neutral glyph, never one vendor's mark (looks pass).
                        LogoTile(logo: nil, systemFallback: "bubble.left.and.bubble.right")
                    } else {
                        SourceLogoTile(origin: tile.origin)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: state.ticked ? "checkmark.circle.fill" : "circle")
                        .font(CicadaTheme.font(size: 15))
                        .foregroundStyle(state.ticked ? CicadaTheme.success : CicadaTheme.textTertiary)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(tile.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    // What a tick reads and the consent it leads to, visible before the click (fix round 2026-10-22).
                    if case .tick(let entry) = tile.kind,
                       let caption = denied.contains(entry.id) ? Copy.Permission.deniedTile
                                     : SourceTiles.caption(entry, needsAccess: needsAccess.contains(entry.id)) {
                        // Looks pass 2 (review of #446): never cut — a consent caption is read before the tick.
                        Text(caption).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    // The ring already says Off (DR-38): the word shows only when it says more, and keeps its
                    // line either way so every tile in a row stays one height.
                    StatusWord(word: state.word, tone: state.tone)
                        .opacity(state.tone != .off || tile.kind == .chats ? 1 : 0)
                        .accessibilityHidden(true)
                }
            }
            .padding(CicadaTheme.spacingSM)
            // A tile grows with its caption, and every tile in its row grows with it (the grid sizes a row by its tallest
            // cell; `maxHeight: .infinity` fills that), so a row stays one height without cutting a word.
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(OnboardingLayout.sourceTileHeight),
                   maxHeight: .infinity, alignment: .topLeading)
            .background(state.ticked ? CicadaTheme.bgSelected : CicadaTheme.bgFocus,
                        in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(help(tile))
        .accessibilityLabel(tile.title)
        .accessibilityValue(state.word)
        .accessibilityAddTraits(state.ticked ? [.isSelected] : [])
    }

    private struct TileState { let ticked: Bool; let word: String; let tone: StatusWord.Tone }

    private func state(of tile: SourceTile) -> TileState {
        switch tile.kind {
        case .tick(let entry):
            let phase = snapshots[entry.id]?.phase
            let status = SourceTiles.status(phase: phase)
            return TileState(ticked: SourceTiles.isTicked(entry, phase: phase), word: status.word, tone: status.tone)
        case .open(let entry):
            let status = SourceTiles.status(catalog: catalogRow(entry).status)
            return TileState(ticked: status.tone == .on, word: status.word, tone: status.tone)
        case .chats:
            // Lit while a file hovers the window (its one drop target), like the old drop zone.
            let status = SourceTiles.chatsStatus(phases: droppedPhases)
            return TileState(ticked: status.tone == .on || dropTargeted, word: status.word, tone: status.tone)
        }
    }

    /// The consent a tick leads to, in the entry's own words (the macOS prompt it names, R-OB7) — never a prompt
    /// raised by hovering.
    private func help(_ tile: SourceTile) -> String {
        switch tile.kind {
        case .tick(let entry): entry.idleLine ?? entry.meta ?? tile.title
        case .open: tile.title
        case .chats: Copy.importDropDetail
        }
    }

    private var droppedPhases: [SetupRowPhase] {
        snapshots.values.compactMap { snapshot in
            if case .dropped = snapshot.id { return snapshot.phase }
            return nil
        }
    }

    private func press(_ tile: SourceTile) {
        switch tile.kind {
        case .tick(let entry):
            // macOS never asks twice: a refused Calendar or Contacts opens its own list instead of ticking again.
            if denied.contains(entry.id), let url = SourceTileGroups.deniedSettingsURL(entry.id) {
                NSWorkspace.shared.open(url)
                return
            }
            let phase = snapshots[entry.id]?.phase
            switch ImportRows.control(entry, phase: phase) {
            case .tick(let on): onTick(entry, !on)
            case .locked, .done: break
            }
        case .open(let entry):
            opened = entry
        case .chats:
            Self.chooseFile(intake)
        }
    }

    private func catalogRow(_ entry: SourceCatalogEntry) -> SourceCatalogRow {
        SourceCatalog.rows(entries: [entry], channels: store.channels.value ?? [],
                           overview: store.sourcesOverview.value ?? [], readableSites: reading.readableSites)[0]
    }

    /// The file panel the old Import page ran: the URLs go to the one intake, which stages them while onboarding
    /// shows (R-IB15). ⌘⇧I and the menu bar's *Import a file…* land here too (`welcomeChooseRequest`).
    static func chooseFile(_ intake: IntakeRouter) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml, .propertyList]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        guard panel.runModal() == .OK else { return }
        intake.accept(urls: panel.urls, from: .welcome)
    }
}

enum SourcesStepLayout {
    /// The Sources page's detail over onboarding: its head, its control and a first look at what came in.
    static let sheetHeight: CGFloat = 380
}
