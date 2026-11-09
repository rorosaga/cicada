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
                if !reader.pending.isEmpty {
                    BookChoiceList(items: reader.pending.map {
                        BookChoiceItem(id: $0.assetId, title: $0.title ?? "", author: $0.author ?? "",
                                       cover: reader.coverFile(for: $0.assetId).map { .file($0) })
                    }, onLeaveOut: { _ in run { await reader.addChosen([]) } }) { ids in
                        run { await reader.addChosen(ids) }
                    }
                }
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

/// 2026-11-08 — Google Books, an optional source that runs only with the person's own key. Off by default; says what it
/// does and that it costs nothing; a link to where the key is made, a field, Save; once on, a one-click Remove in the
/// footer. A refused key or a closed quota says its fix in words beside the field. DR-5 (one primary), DR-38 (said
/// once), DR-59 (the state in one line).
struct GoogleBooksKeySlot: View {
    let slot: SourceSlot
    @State private var model = GoogleBooksKeyModel.shared
    @State private var key = ""
    @FocusState private var focused: Bool
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            switch slot {
            case .connect: connectArea
            case .footer:
                if model.connected {
                    SourcePageFooter(actions: [
                        .disconnect(Copy.googleBooksTitle, message: Copy.googleBooksDisconnectKeeps) {
                            Task {
                                await model.remove()
                                await store.refresh([.sources, .sourcesOverview, .status])
                            }
                        },
                    ])
                }
            }
        }
        .task { await model.refresh() }
    }

    @ViewBuilder
    private var connectArea: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let status = model.status {
                Text(status.whatItDoes + " " + status.freeWords)
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if status.connected {
                    SourceConnectLine(text: Copy.googleBooksOn)
                } else {
                    keyEntry(status)
                }
                if let words = status.problemWords {
                    Text(words).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func keyEntry(_ status: GoogleBooksKeyStatus) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SecureField("", text: $key)
                    .focused($focused)
                    .cicadaField(isFocused: focused, prompt: Copy.googleBooksKeyPrompt, isEmpty: key.isEmpty)   // DR-76
                    .onSubmit { save() }
                    .disabled(model.saving)
                if model.saving { ProgressView().controlSize(.small) }
                NeutralButton(title: Copy.googleBooksSave, size: .compact,
                              isDisabled: model.saving || key.trimmingCharacters(in: .whitespaces).isEmpty) { save() }
            }
            if let url = URL(string: status.keyUrl), url.scheme == "https" {
                TextButton(title: Copy.googleBooksMakeKey, inline: true) { NSWorkspace.shared.open(url) }
            }
            if let failure = model.failure {
                Text(failure).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func save() {
        let candidate = key.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            if await model.save(candidate) {
                key = ""
                await store.refresh([.sources, .sourcesOverview, .status])
            }
        }
    }
}

/// Ruling 61 — a book's row in a source's list: its cover, whole, in the row's slot, or an empty slot. DR-9 (a ring,
/// not a border), DR-12 (corners that scale), owner 2026-10-28 (no stand-in). Asked only when its row is drawn.
struct BookCoverThumb: View {
    let path: String?
    /// 40 pt in a row; the page's head and the Add's result draw it larger.
    var points: CGFloat = 40
    /// A row keeps its slot so titles align; the page's head takes none until the picture has loaded (no empty box).
    var reservesSlot = true
    /// Space after the picture, only once it is drawn.
    var trailing: CGFloat = 0
    /// The page's head asks ahead of the rows (`SourcePictureStore.image(priority:)`).
    var priority = false

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        let height = CicadaTheme.scaled(points)
        let drawn = image != nil || reservesSlot
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
        // Top-aligned: a cover that is not exactly 2:3 sits at the top of its slot, level with the text beside it on a
        // book's page, instead of floating in the slot's middle (the `HStack` is `.top`, the picture was centred).
        .frame(width: drawn ? height * 2 / 3 : 0, height: drawn ? height : 0, alignment: .top)
        .padding(.trailing, image != nil ? trailing : 0)
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(path ?? "")") {
            guard let path else { image = nil; return }
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "", priority: priority)
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
    /// ROR-138: a list row draws its cover from `/entities/<id>/preview`, so the head asks the same place when the
    /// page itself named none (it draws nothing on a 404, `reservesSlot: false`).
    /// `open=1` — the page the person opened asks through its own slots, never behind the list rows' first fetches.
    private var coverPath: String {
        let path = cover ?? "/entities/\(entityId)/preview"
        return path + (path.contains("?") ? "&" : "?") + "open=1"
    }
    /// The page's markdown: its `## Summary` is the description the box under the head draws.
    var markdown: String = ""
    let changed: () -> Void

    @State private var card: BookCard?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            head
            if let description = EntityHeaderWords.bookDescription(markdown) {
                BookDescriptionBox(entityId: entityId, description: description,
                                   byTitle: card?.matchedByTitle == true, why: card?.why, changed: changed)
            }
        }
        .task(id: entityId) { card = try? await APIClient.shared.fetchBookCard(id: entityId) }
    }

    private var head: some View {
        HStack(alignment: .top, spacing: 0) {
            BookCoverThumb(path: coverPath, points: 168, reservesSlot: false, trailing: CicadaTheme.spacingLG, priority: true)
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
    }
}

/// A book's description, below its head: a small settled summary with its source named, no heading and no fold (the page is
/// an article, DR-77; said once, DR-38; a ring, not a border, DR-9). It is a world fact from a public source, never the
/// person's words — the source and the day it was saved say so — and a book a title found says that too, with the way
/// back ("Not this book"), which removes the description and is never asked again.
struct BookDescriptionBox: View {
    let entityId: String
    let description: EntityHeaderWords.BookDescription
    let byTitle: Bool
    var why: String? = nil
    let changed: () -> Void

    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(description.text)
                .font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let why {
                Text(why).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if let name = description.source {
                    let line = Copy.bookDescriptionSource(name, saved: description.saved)
                    if let url = description.url.flatMap(URL.init(string:)) {
                        Link(line, destination: url)
                    } else {
                        Text(line)
                    }
                }
                if byTitle {
                    Text("·")
                    Text(Copy.bookFoundByTitle)
                    NeutralButton(title: Copy.bookNotThisBook) {
                        busy = true
                        Task {
                            try? await APIClient.shared.notThisBook(id: entityId)
                            busy = false
                            changed()
                        }
                    }
                    .disabled(busy)
                }
            }
            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
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

/// G233 — Goodreads has no open API since 2020. The way in is the person's own agent reading their shelves in their own
/// browser (ROR-128; the books wait in `GoodreadsWaitingList` for the person's pick), and, quietly after it, the
/// person's own "Export Library" file: *Import a file* (where the file comes from on its hover), then what it holds in
/// counts beside *Import*.
struct GoodreadsSlot: View {
    /// ROR-128 (owner 2026-11-06: "the browser should be there before exporting a file"): the person's own agent reads
    /// their shelves in their browser — the page's *Read through your browser* switch comes first, the file after it.
    var browserWay: SourceWayIn?
    @Environment(Store.self) private var store
    @State private var picking = false
    @State private var file: (data: Data, name: String)?
    @State private var preview: GoodreadsPreview?
    @State private var line: BooksRowText.Line?
    @State private var busy = false

    var body: some View {
        SourceConnectArea(primary: nil, line: line?.text, lineIsAttention: line?.isProblem ?? false,
                          ways: (browserWay.map { [$0] } ?? []) + [chooseWay]) {
            GoodreadsWaitingList()
            if let preview, !preview.items.isEmpty {
                BookChoiceList(items: preview.items.map {
                    BookChoiceItem(id: $0.id, title: $0.title, author: $0.author,
                                   cover: $0.isbn.isEmpty ? nil : .isbn($0.isbn))
                }, busy: busy) { ids in Task { await runImport(ids: ids) } }
            } else if preview != nil {
                PrimaryActionButton(title: Copy.goodreadsImport) { Task { await runImport(ids: nil) } }
                    .disabled(busy).fixedSize()
            }
        }
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

    private func runImport(ids: Set<String>?) async {
        guard let file else { return }
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.importGoodreads(data: file.data, filename: file.name,
                                                              ids: ids.map { Array($0).sorted() })
            line = .init(text: Copy.goodreadsImported(result.books))
            preview = nil
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        } catch {
            line = .init(text: Copy.goodreadsFailed, isProblem: true)
        }
    }
}

extension APIClient: AppleBooksSyncAPI {}
