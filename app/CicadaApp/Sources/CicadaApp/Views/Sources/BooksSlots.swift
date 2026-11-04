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
            let line = BooksRowText.appleBooks(reader.status, lastError: channel?.lastError)
            if reader.enabled {
                SourceConnectArea(line: line?.text, lineIsAttention: line?.isProblem ?? false)
            } else {
                // A first read that failed before the reader came on keeps Connect, with why beside it.
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect(Copy.appleBooksTitle),
                                                               help: Copy.appleBooksConnectHelp) {
                    run { await reader.turnOn() }
                }, line: line?.text, lineIsAttention: line?.isProblem ?? false)
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

    /// The reader's act, then the page's status and list read again.
    private func run(_ act: @escaping () async -> Void) {
        Task {
            await act()
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
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
