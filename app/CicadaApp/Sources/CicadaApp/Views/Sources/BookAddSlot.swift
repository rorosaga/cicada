import SwiftUI

// ROR-116, G233 — Sources → Reading → Book scans: add a book on the Mac, by number or by this Mac's camera, through the
// phone's own `POST /capture/isbn`. DR-5 (one primary: Add), DR-9 (a ring, not a border), DR-34 (heights from tokens),
// DR-38 (said once), DR-41 (a disabled button keeps its label), DR-59 (one line; no paragraph).

/// "A number was read": the one function behind the Add. The field, the camera and any other reader call
/// ``submit(_:status:)`` with the number as read; the result is what the Add shows (the book it found, or one line).
@MainActor @Observable
final class BookAddFlow {
    static let shared = BookAddFlow()

    private(set) var line: BooksRowText.Line?
    /// The book the number became, once the home has looked it up: the Add draws it and opens its page.
    private(set) var found: BookScanResult?
    /// Numbers sent whose lookup has not answered. The Add waits on it; the scanner does not — it takes the next book
    /// while the last is looked up, so `submit` can be called again before an earlier call returns.
    private var pending = 0
    var busy: Bool { pending > 0 }

    /// Sends the number as the phone's `POST /capture/isbn` does, then follows what it became a few times (the lookup
    /// runs at the home; a slow one lands on its own). True when the number was accepted. `onFound` hears the book as
    /// soon as the lookup answers, or nil when it has not by the time the follow gives up.
    @discardableResult
    func submit(_ raw: String, status: String? = nil, onFound: ((BookScanResult?) -> Void)? = nil) async -> Bool {
        guard let isbn = BookISBN.parse(raw) else {
            line = .init(text: Copy.bookAddNotABook, isProblem: true)
            return false
        }
        pending += 1
        defer { pending -= 1 }
        found = nil
        do {
            let sent = try await APIClient.shared.captureISBN(isbn, status: status)
            line = .init(text: Copy.bookAddWaiting)
            let result = await follow(sent.episodeId)
            if let result { found = result; line = nil }
            onFound?(result)
            return true
        } catch {
            line = .init(text: Copy.bookAddFailed, isProblem: true)
            return false
        }
    }

    func clear() { line = nil; found = nil }

    private func follow(_ episodeId: String?) async -> BookScanResult? {
        guard let episodeId else { return nil }
        for _ in 0..<12 {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard let result = try? await APIClient.shared.bookScanResult(episodeId: episodeId),
                  result.state == "added", result.entityId != nil, result.name != nil else { continue }
            return result
        }
        return nil
    }
}

/// The book a number became: its small cover, title and authors in one row that opens the book's page (never the scan's
/// own record). DR-48 (a fill on hover), DR-59 (two lines at most).
private struct BookFoundRow: View {
    let result: BookScanResult
    @Environment(AppRouter.self) private var router
    @State private var hovering = false

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        Button {
            if let id = result.entityId { router.routeToEntity(id) }
        } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                if result.cover != nil { BookCoverThumb(path: result.cover, points: 56) }
                VStack(alignment: .leading, spacing: 2) {
                    Text(result.name ?? "").font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Text(BooksRowText.found(authors: result.authors ?? [], existing: result.existing == true))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(CicadaTheme.spacingSM)
            .background { if hovering { shape.fill(CicadaTheme.ring(.resting)) } }
            .contentShape(shape)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .accessibilityLabel(result.name ?? "")
    }
}

/// The Add on the Book scans page. A number typed, pasted or read from the camera; the status the person says (or none);
/// the result in one line — "Added · <title>", or "Already in your books · <title>" with a way to open that page.
struct BookAddSlot: View {
    @Environment(Store.self) private var store
    @State private var scanOpen = false
    @State private var text = ""
    @State private var status: String?
    @FocusState private var focused: Bool

    private var flow: BookAddFlow { .shared }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $text)
                    .focused($focused)
                    .cicadaField(isFocused: focused, prompt: Copy.bookAddPrompt, isEmpty: text.isEmpty)
                    .frame(width: CicadaTheme.scaled(180))
                    .onSubmit { Task { await add() } }
                ForEach(Copy.bookAddStatuses, id: \.key) { option in
                    BookStatusChip(label: option.label, isOn: status == option.key) {
                        status = status == option.key ? nil : option.key
                    }
                }
                NeutralButton(title: Copy.bookAdd, size: .compact,
                              isDisabled: flow.busy || BookISBN.parse(text) == nil) { Task { await add() } }
                NeutralButton(title: Copy.bookAddScan, systemImage: "barcode.viewfinder", size: .compact,
                              help: Copy.bookAddScanHelp) {
                    flow.clear()
                    scanOpen = true   // The person's click: the camera opens inside the window, nowhere else.
                }
                Spacer(minLength: 0)
            }
            if let message = flow.line?.text {
                SourceConnectLine(text: message, isAttention: flow.line?.isProblem ?? false)
            }
            if let found = flow.found { BookFoundRow(result: found) }
        }
        // The scanner is its own window over the app: it owns the camera, and closing it (Esc, its button, the page
        // going away) stops it.
        .sheet(isPresented: $scanOpen) {
            BookScanSheet { await store.refresh([.channels, .sources, .sourcesOverview, .status]) }
        }
    }

    private func add() async {
        let sent = text
        let chosen = status
        if await flow.submit(sent, status: chosen) {
            text = ""
            status = nil
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }
}

/// One of the three things a person says about a book they add; tapping the chosen one again says nothing.
private struct BookStatusChip: View {
    let label: String
    let isOn: Bool
    let action: () -> Void

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        Button(action: action) {
            Text(label)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(isOn ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .frame(height: CicadaTheme.scaled(28))
                .background { if isOn { shape.fill(CicadaTheme.ring(.resting)) } }
                .overlay { shape.stroke(CicadaTheme.ring(isOn ? .strong : .resting), lineWidth: 1) }
                .contentShape(shape)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}
