import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// G39 — Apple Books on the Sources page → Reading: read by the APP (`AppleBooksReader`) only after Turn on, one way.
/// `RemindersRow`'s layout (DR-40 `NeutralButton(size: .compact)`, Turn off behind a confirmation). The mark is the
/// installed Apple Books app's own icon (DR-52; Apple's marks are never committed).
struct AppleBooksRow: View {
    let channel: SourceChannel?
    @Environment(AppleBooksReader.self) private var reader
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var confirmStop = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                if !headShown {
                    LogoImage.platformTile(name: "",
                                           bundleId: OriginIconography.appBundleId(for: AppleBooksReader.channel),
                                           size: CicadaTheme.scaled(28),
                                           systemFallback: OriginIconography.symbol(for: AppleBooksReader.channel))
                }
                VStack(alignment: .leading, spacing: 2) {
                    if !headShown {
                        Text(Copy.appleBooksTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    Text(line)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(isProblem ? CicadaTheme.danger : CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                actions
            }
            if reader.enabled {
                Text(Copy.appleBooksReads).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .confirmationDialog(Copy.appleBooksStopTitle, isPresented: $confirmStop) {
            Button(Copy.appleBooksTurnOff, role: .destructive) { Task { await reader.turnOff() } }
            Button(Copy.cancelAction, role: .cancel) {}
        } message: {
            Text(Copy.appleBooksStopDetail)
        }
    }

    private var line: String {
        if case .synced = reader.status, let error = channel?.lastError, !error.isEmpty { return error }
        return BooksRowText.appleBooks(reader.status, now: Date())
    }

    private var isProblem: Bool {
        if case .failed = reader.status { return true }
        return false
    }

    @ViewBuilder
    private var actions: some View {
        switch reader.status {
        case .off:
            NeutralButton(title: Copy.appleBooksTurnOn, size: .compact) { Task { await reader.turnOn() } }
        case .syncing:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact, isDisabled: true,
                          disabledHelp: Copy.appleBooksSyncing) {}
            NeutralButton(title: Copy.appleBooksTurnOff, size: .compact) { confirmStop = true }
        case .synced, .failed:
            NeutralButton(title: Copy.calendarSyncNow, size: .compact) { Task { await reader.syncNow() } }
            NeutralButton(title: Copy.appleBooksTurnOff, size: .compact) { confirmStop = true }
        }
    }
}

/// G233 — a Goodreads export: where it comes from, then Choose → what it holds, in counts → Import. Goodreads has no
/// open API since 2020, so the person's own "Export Library" file is the one way in; nothing is read from the site.
struct GoodreadsImportRow: View {
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var picking = false
    @State private var file: (data: Data, name: String)?
    @State private var preview: GoodreadsPreview?
    @State private var line: String?
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.goodreadsHow).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.goodreadsChoose, size: .compact, isDisabled: busy) { picking = true }
                if preview != nil {
                    NeutralButton(title: Copy.goodreadsImport, size: .compact, isDisabled: busy) {
                        Task { await runImport() }
                    }
                }
            }
            if let line {
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .fileImporter(isPresented: $picking, allowedContentTypes: [.commaSeparatedText, .plainText]) { result in
            guard case .success(let url) = result else { return }
            Task { await choose(url) }
        }
    }

    private func choose(_ url: URL) async {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else { line = Copy.goodreadsFailed; return }
        busy = true
        line = Copy.goodreadsReading
        defer { busy = false }
        do {
            let p = try await APIClient.shared.previewGoodreads(data: data, filename: url.lastPathComponent)
            file = (data, url.lastPathComponent)
            preview = p
            line = BooksRowText.goodreadsPreview(p)
        } catch {
            preview = nil
            line = Copy.goodreadsFailed
        }
    }

    private func runImport() async {
        guard let file else { return }
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.importGoodreads(data: file.data, filename: file.name)
            line = Copy.goodreadsImported(result.books)
            preview = nil
        } catch {
            line = Copy.goodreadsFailed
        }
    }
}

extension APIClient: AppleBooksSyncAPI {}
