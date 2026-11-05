import AppKit
import SwiftUI
import UniformTypeIdentifiers

// Sources → Reading on the standard source page (`SourcePageLayout`, DESIGN_RULES §9 2026-11-04). DR-5 (one primary),
// DR-38 (said once), DR-52 (the installed app's own icon; Apple's marks are never committed), DR-59 (one line).

/// G39 — Apple Books: Connect turns the reader on and starts the first read (macOS asks then, never before the click);
/// on, the area's one line says what came in, and the footer holds Refresh and Disconnect.
struct AppleBooksSlot: View {
    let slot: SourceSlot
    let channel: SourceChannel?
    @Environment(AppleBooksReader.self) private var reader
    @Environment(Store.self) private var store

    var body: some View {
        switch slot {
        case .connect:
            // G233: a book is added here too (the owner looked for the number and the camera on this page).
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                connectArea
                BookAddSlot()
            }
        case .footer:
            if reader.enabled {
                SourcePageFooter(actions: [
                    .refresh(isDisabled: reader.status == .syncing) { run { await reader.syncNow() } },
                    .disconnect(Copy.appleBooksTitle) { run { await reader.turnOff() } },
                ])
            }
        }
    }

    @ViewBuilder
    private var connectArea: some View {
        let line = BooksRowText.appleBooks(reader.status, lastError: channel?.lastError)
        if reader.enabled && reader.deniedByMac {
            SourceConnectArea(primary: SourcePrimaryAction(title: Copy.allowFullDiskAccess) {
                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
            }, line: line?.text, lineIsAttention: true)
        } else if reader.enabled {
            SourceConnectArea(line: line?.text, lineIsAttention: line?.isProblem ?? false)
        } else {
            // A first read that failed before the reader came on keeps Connect, with why beside it.
            SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect(Copy.appleBooksTitle),
                                                           help: Copy.appleBooksConnectHelp) {
                run { await reader.turnOn() }
            }, line: line?.text, lineIsAttention: line?.isProblem ?? false)
        }
    }

    /// The reader's act, then the page's status and list read again.
    private func run(_ act: @escaping () async -> Void) {
        Task {
            await act()
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }
}

/// Ruling 61 — a book's row in a source's list: its cover, whole, in the row's slot, or an empty slot. DR-9 (a ring,
/// not a border), DR-12 (corners that scale), owner 2026-10-28 (no stand-in). Asked only when its row is drawn.
struct BookCoverThumb: View {
    let path: String?
    /// 40 pt in a row; the page's head and the Add's result draw it larger.
    var points: CGFloat = 40

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        let height = CicadaTheme.scaled(points)
        let shape = CicadaTheme.shape(CicadaTheme.scaled(3))
        Group {
            if let image {
                Image(nsImage: image).resizable().interpolation(.high).aspectRatio(contentMode: .fit)
                    .clipShape(shape)
                    .overlay { shape.stroke(CicadaTheme.ring(.resting), lineWidth: 1) }
            } else {
                Color.clear
            }
        }
        .frame(width: height * 2 / 3, height: height)
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(path ?? "")") {
            guard let path else { image = nil; return }
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "")
        }
    }
}

/// G233 — a book's page leads with the book: its cover at a real size (none, no empty box), then subtitle, authors, one
/// line of year, pages and publisher, the ways it came in as small labels, and where the person stands with it. The
/// title is the card's own header. DR-59 (one line each), DR-38 (said once), DR-9 (a ring, not a border).
struct BookPageHead: View {
    let entityId: String
    /// The page's own picture path (`media.preview`), nil for a book with no cover.
    let cover: String?
    let changed: () -> Void

    @State private var card: BookCard?

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
            if cover != nil { BookCoverThumb(path: cover, points: 168) }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                if let subtitle = card?.subtitle {
                    Text(subtitle).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                if let authors = card?.authors, !authors.isEmpty {
                    Text(authors.joined(separator: ", ")).font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                }
                if let facts = card?.factsLine {
                    Text(facts).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                if let ways = card?.ways, !ways.isEmpty {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        ForEach(ways, id: \.door) { way in
                            Text(BooksRowText.way(way))
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                                .frame(height: CicadaTheme.scaled(20))
                                .overlay { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                                    .stroke(CicadaTheme.ring(.resting), lineWidth: 1) }
                        }
                    }
                }
                BookStatusLine(entityId: entityId, changed: changed)
                if let subjects = card?.subjects, !subjects.isEmpty {
                    Text(subjects.joined(separator: " · ")).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task(id: entityId) { card = try? await APIClient.shared.fetchBookCard(id: entityId) }
    }
}

/// Ruling 61 — the book's status at the head of its page, in one line, and "Not right" when a conversation set it. DR-59
/// (one line), DR-38 (said once), DR-31 (the conversation it came from opens the one Reader, from the page's sources).
struct BookStatusLine: View {
    let entityId: String
    /// After a take-back: the page's article and claims read again.
    let changed: () -> Void

    @State private var record: BookStatusRecord?
    @State private var failed = false

    var body: some View {
        Group {
            if let record {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(BooksRowText.status(record))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(failed ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    if record.fromChat {
                        TextButton(title: Copy.bookStatusNotRight, help: Copy.bookStatusNotRightHelp, inline: true) {
                            Task { await undo(record) }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .task(id: entityId) { await load() }
    }

    private func load() async {
        record = try? await APIClient.shared.fetchBookStatus(id: entityId)
    }

    private func undo(_ record: BookStatusRecord) async {
        do {
            try await APIClient.shared.undoBookStatus(id: entityId, claimId: record.claimId)
            failed = false
            await load()
            changed()
        } catch {
            failed = true
        }
    }
}

/// G233 — a Goodreads export: Goodreads has no open API since 2020, so the person's own "Export Library" file is the
/// one way in and nothing is read from the site. *Import a file* (where the file comes from on its hover), then what
/// it holds in counts beside *Import*.
struct GoodreadsSlot: View {
    @Environment(Store.self) private var store
    @State private var picking = false
    @State private var file: (data: Data, name: String)?
    @State private var preview: GoodreadsPreview?
    @State private var line: BooksRowText.Line?
    @State private var busy = false

    var body: some View {
        SourceConnectArea(primary: preview == nil ? nil : SourcePrimaryAction(title: Copy.goodreadsImport,
                                                                              isDisabled: busy) {
            Task { await runImport() }
        }, line: line?.text, lineIsAttention: line?.isProblem ?? false, ways: [chooseWay])
        .fileImporter(isPresented: $picking, allowedContentTypes: [.commaSeparatedText, .plainText]) { result in
            guard case .success(let url) = result else { return }
            Task { await choose(url) }
        }
    }

    private var chooseWay: SourceWayIn {
        var way = SourceWayIn.importFile(origin: "goodreads", help: SourceCatalog.exportHow("goodreads")) {
            picking = true
        }
        way.isDisabled = busy
        return way
    }

    private func choose(_ url: URL) async {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        preview = nil
        guard let data = try? Data(contentsOf: url) else {
            line = .init(text: Copy.goodreadsFailed, isProblem: true)
            return
        }
        busy = true
        line = .init(text: Copy.goodreadsReading)
        defer { busy = false }
        do {
            let p = try await APIClient.shared.previewGoodreads(data: data, filename: url.lastPathComponent)
            file = (data, url.lastPathComponent)
            preview = p
            line = .init(text: BooksRowText.goodreadsPreview(p))
        } catch {
            line = .init(text: Copy.goodreadsFailed, isProblem: true)
        }
    }

    private func runImport() async {
        guard let file else { return }
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.importGoodreads(data: file.data, filename: file.name)
            line = .init(text: Copy.goodreadsImported(result.books))
            preview = nil
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        } catch {
            line = .init(text: Copy.goodreadsFailed, isProblem: true)
        }
    }
}

extension APIClient: AppleBooksSyncAPI {}
