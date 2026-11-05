import SwiftUI

// ROR-116, G233 — Sources → Reading → Book scans: add a book on the Mac, by number or by this Mac's camera, through the
// phone's own `POST /capture/isbn`. DR-5 (one primary: Add), DR-9 (a ring, not a border), DR-34 (heights from tokens),
// DR-38 (said once), DR-41 (a disabled button keeps its label), DR-59 (one line; no paragraph).

/// The Add on the Book scans page. A number typed, pasted or read from the camera; the status the person says (or none);
/// the result in one line — "Added · <title>", or "Already in your books · <title>" with a way to open that page.
struct BookAddSlot: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @State private var camera = BookBarcodeCamera()
    @State private var text = ""
    @State private var status: String?
    @State private var busy = false
    @State private var line: BooksRowText.Line?
    @State private var openId: String?
    @FocusState private var focused: Bool

    private var scanning: Bool { camera.state == .starting || camera.state == .running }

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
                              isDisabled: busy || BookISBN.parse(text) == nil) { Task { await add() } }
                NeutralButton(title: scanning ? Copy.bookAddStopScan : Copy.bookAddScan,
                              systemImage: "barcode.viewfinder", size: .compact, help: Copy.bookAddScanHelp) {
                    if scanning { camera.stop() } else { scan() }
                }
                Spacer(minLength: 0)
            }
            if scanning {
                let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                BookCameraPreview(session: camera.session)
                    .frame(maxWidth: CicadaTheme.scaled(320))
                    .frame(height: CicadaTheme.scaled(180))
                    .clipShape(shape)
                    .overlay { shape.stroke(CicadaTheme.ring(.resting), lineWidth: 1) }
                    .accessibilityHidden(true)
            }
            if let message = cameraLine ?? line?.text {
                HStack(spacing: CicadaTheme.spacingSM) {
                    SourceConnectLine(text: message, isAttention: cameraLine != nil || (line?.isProblem ?? false))
                    if let openId {
                        TextButton(title: Copy.bookAddOpen, inline: true) { router.routeToEntity(openId) }
                    }
                }
            }
        }
        .onDisappear { camera.stop() }
    }

    /// The one fix when the camera cannot open, in words.
    private var cameraLine: String? {
        switch camera.state {
        case .denied: Copy.bookAddCameraDenied
        case .unavailable: Copy.bookAddNoCamera
        default: nil
        }
    }

    /// The person's click: the camera opens (macOS asks now, if it has not), and the first book's number fills the field
    /// with the camera already stopped — the person confirms the status and presses Add.
    private func scan() {
        line = nil
        openId = nil
        camera.onISBN = { isbn in
            text = isbn
            focused = false
        }
        Task { await camera.start() }
    }

    private func add() async {
        guard let isbn = BookISBN.parse(text), !busy else {
            line = .init(text: Copy.bookAddNotABook, isProblem: true)
            return
        }
        busy = true
        defer { busy = false }
        camera.stop()
        openId = nil
        do {
            let sent = try await APIClient.shared.captureISBN(isbn, status: status)
            line = .init(text: Copy.bookAddWaiting)
            text = ""
            status = nil
            await follow(sent.episodeId)
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        } catch {
            line = .init(text: Copy.bookAddFailed, isProblem: true)
        }
    }

    /// The lookup runs at the home; ask what the scan became a few times, then leave it waiting (it lands on its own).
    private func follow(_ episodeId: String?) async {
        guard let episodeId else { return }
        for _ in 0..<12 {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard let result = try? await APIClient.shared.bookScanResult(episodeId: episodeId),
                  result.state == "added", let name = result.name else { continue }
            line = .init(text: result.existing == true ? Copy.bookAddAlready(name) : Copy.bookAddAdded(name))
            openId = result.entityId
            return
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
