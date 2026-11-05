import SwiftUI

// G233 — the book scanner: this Mac's camera in a window over the app, the way the iPhone scans a document. It outlines
// the book it sees (the rest dimmed), locks a tighter mark onto the barcode's own corners, takes the number by itself
// and keeps looking for the next book. DR-9 (a ring, not a shadow), DR-59 (one line at most, no paragraph), DR-60 (Esc
// never animates), DR-61 (durations in `CicadaMotion`), DR-66 (Reduce Motion drops the movement, keeps a short fade).
// The highlight is white on the feed, not the accent: it is not one of the accent's six uses (DR §3.3).

/// What the window draws of the camera's latest frames, held steady (`QuadHold`).
@MainActor @Observable
final class BookScanScene {
    private(set) var frame = ScanFrame(imageSize: .zero)
    @ObservationIgnored private var barcodeHold = QuadHold()
    @ObservationIgnored private var bookHold = QuadHold()

    func update(_ new: ScanFrame, now: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        frame = ScanFrame(imageSize: new.imageSize,
                          barcode: barcodeHold.update(new.barcode, at: now),
                          barcodeIsBook: new.barcode != nil ? new.barcodeIsBook : frame.barcodeIsBook,
                          book: bookHold.update(new.book, at: now))
    }
}

/// One book taken in this window: its number now, its title and cover once the home has looked it up.
private struct ScanEntry: Identifiable {
    let id = UUID()
    let isbn: String
    var result: BookScanResult?
    var looked = false
}

struct BookScanSheet: View {
    /// Called after each book is accepted, so the page behind lists it.
    let refreshed: () async -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(AppRouter.self) private var router
    @State private var camera = BookBarcodeCamera()
    @State private var scene = BookScanScene()
    @State private var entries: [ScanEntry] = []
    @State private var notice: String?
    @State private var noticeToken = 0
    @State private var locked = false
    @State private var lockToken = 0
    @State private var away: Task<Void, Never>?

    var body: some View {
        ZStack {
            Color.black
            BookCameraPreview(session: camera.session, mirrored: camera.mirrored).accessibilityHidden(true)
            ScanHighlights(scene: scene, mirrored: camera.mirrored, locked: locked, reduceMotion: reduceMotion)
            if let line = cameraLine {
                Text(line).font(CicadaTheme.rowFont).foregroundStyle(Color.white.opacity(0.9))
                    .multilineTextAlignment(.center).padding(CicadaTheme.spacingLG)
            }
            VStack(spacing: CicadaTheme.spacingSM) {
                HStack {
                    if !entries.isEmpty {
                        Text(Copy.bookScanCount(entries.count)).font(CicadaTheme.metaMediumFont)
                            .foregroundStyle(Color.white.opacity(0.9)).padding(.horizontal, CicadaTheme.spacingMD)
                            .frame(height: CicadaTheme.scaled(28)).background(Capsule().fill(Color.black.opacity(0.5)))
                    }
                    Spacer(minLength: 0)
                    closeButton
                }
                Spacer(minLength: 0)
                if let notice {
                    Text(notice).font(CicadaTheme.metaMediumFont).foregroundStyle(Color.white)
                        .padding(.horizontal, CicadaTheme.spacingMD).frame(height: CicadaTheme.scaled(28))
                        .background(Capsule().fill(Color.black.opacity(0.6)))
                }
                ForEach(entries.suffix(3)) { entry in
                    ScanEntryCard(entry: entry) {
                        guard let id = entry.result?.entityId else { return }
                        dismiss()
                        router.routeToEntity(id)
                    }
                }
            }
            .padding(CicadaTheme.spacingMD)
        }
        .frame(width: CicadaTheme.scaled(760), height: CicadaTheme.scaled(560))
        .task {
            camera.onFrame = { scene.update($0) }
            camera.onEvent = { handle($0) }
            await camera.start()
        }
        .onDisappear {
            camera.stop()
            away?.cancel()
        }
        // Not left watching a room while the person is in another app: a moment away closes the window and the camera.
        // (macOS's own camera prompt also takes the app's focus, so a camera still starting is not "away".)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willResignActiveNotification)) { _ in
            away?.cancel()
            away = Task {
                try? await Task.sleep(nanoseconds: UInt64(CicadaMotion.scanAwayGrace * 1_000_000_000))
                if !Task.isCancelled, camera.state != .starting { dismiss() }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            away?.cancel()
        }
    }

    private var closeButton: some View {
        Button { dismiss() } label: {
            Image(systemName: "xmark").font(CicadaTheme.metaMediumFont).foregroundStyle(Color.white)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .background(Circle().fill(Color.black.opacity(0.5)))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .keyboardShortcut(.cancelAction)
        .help(Copy.bookScanClose)
        .accessibilityLabel(Copy.bookScanClose)
    }

    /// The one fix when the camera cannot open, in words.
    private var cameraLine: String? {
        switch camera.state {
        case .denied: Copy.bookAddCameraDenied
        case .unavailable: Copy.bookAddNoCamera
        default: nil
        }
    }

    private func handle(_ event: ScanEvent) {
        switch event {
        case .notABook:
            show(Copy.bookAddNotABook)
        case .book(let isbn):
            lock()
            let entry = ScanEntry(isbn: isbn)
            entries.append(entry)
            Task {
                let ok = await BookAddFlow.shared.submit(isbn) { result in
                    guard let index = entries.firstIndex(where: { $0.id == entry.id }) else { return }
                    entries[index].result = result
                    entries[index].looked = true
                }
                if ok {
                    await refreshed()
                } else {
                    entries.removeAll { $0.id == entry.id }
                    camera.forget(isbn)   // The capture did not land: reading it again is allowed.
                    show(Copy.bookAddFailed)
                }
            }
        }
    }

    /// The mark on the taken code grows and fills for a moment, then the scanner goes back to looking.
    private func lock() {
        lockToken += 1
        let token = lockToken
        withAnimation(CicadaMotion.scanLock(reduceMotion: reduceMotion)) { locked = true }
        Task {
            try? await Task.sleep(nanoseconds: UInt64(CicadaMotion.scanLockHold * 1_000_000_000))
            guard token == lockToken else { return }
            withAnimation(CicadaMotion.scanLock(reduceMotion: reduceMotion)) { locked = false }
        }
    }

    private func show(_ text: String) {
        noticeToken += 1
        let token = noticeToken
        notice = text
        Task {
            try? await Task.sleep(nanoseconds: UInt64(CicadaMotion.scanNoticeHold * 1_000_000_000))
            if token == noticeToken { notice = nil }
        }
    }
}

/// The outlines. Its own view so the 20-a-second frames redraw this and nothing else.
private struct ScanHighlights: View {
    let scene: BookScanScene
    let mirrored: Bool
    let locked: Bool
    let reduceMotion: Bool

    var body: some View {
        GeometryReader { geo in
            let frame = scene.frame
            let book = frame.book?.viewPoints(imageSize: frame.imageSize, viewSize: geo.size, mirrored: mirrored)
            let code = frame.barcode?.viewPoints(imageSize: frame.imageSize, viewSize: geo.size, mirrored: mirrored)
            ZStack {
                if let book {
                    // The area outside the book dimmed, as a document is masked on the iPhone.
                    Path { path in
                        path.addRect(CGRect(origin: .zero, size: geo.size))
                        path.addPath(Self.polygon(book))
                    }
                    .fill(Color.black.opacity(0.45), style: FillStyle(eoFill: true))
                    Self.polygon(book).stroke(Color.white.opacity(0.85), style: StrokeStyle(lineWidth: 2, lineJoin: .round))
                }
                if let code {
                    let isBook = frame.barcodeIsBook
                    let mark = Self.polygon(code)
                    let centre = Self.centre(code)
                    ZStack {
                        mark.fill(Color.white.opacity(locked ? 0.5 : (isBook ? 0.14 : 0.04)))
                        mark.stroke(Color.white.opacity(isBook ? 1 : 0.5),
                                    style: StrokeStyle(lineWidth: locked ? 4 : 2.5, lineJoin: .round))
                        if locked {
                            Image(systemName: "checkmark").font(CicadaTheme.rowFont).foregroundStyle(Color.white)
                                .position(centre)
                        }
                    }
                    .scaleEffect(locked && !reduceMotion ? 1.06 : 1,
                                 anchor: UnitPoint(x: centre.x / max(geo.size.width, 1), y: centre.y / max(geo.size.height, 1)))
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    static func polygon(_ points: [CGPoint]) -> Path {
        var path = Path()
        guard let first = points.first else { return path }
        path.move(to: first)
        points.dropFirst().forEach { path.addLine(to: $0) }
        path.closeSubpath()
        return path
    }

    static func centre(_ points: [CGPoint]) -> CGPoint {
        let n = CGFloat(max(points.count, 1))
        return CGPoint(x: points.map(\.x).reduce(0, +) / n, y: points.map(\.y).reduce(0, +) / n)
    }
}

/// A book taken in this window: cover, title, authors — or "Looking it up" until the home answers. A ring, not a shadow.
private struct ScanEntryCard: View {
    let entry: ScanEntry
    let open: () -> Void

    var body: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingMD) {
                if entry.result?.cover != nil { BookCoverThumb(path: entry.result?.cover, points: 44) }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(CicadaTheme.rowFont).foregroundStyle(Color.white).lineLimit(1)
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(Color.white.opacity(0.7)).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: CicadaTheme.scaled(420), alignment: .leading)
            .background(shape.fill(Color.black.opacity(0.6)))
            .overlay { shape.stroke(Color.white.opacity(0.12), lineWidth: 1) }
            .contentShape(shape)
        }
        .buttonStyle(.plain)
        .disabled(entry.result?.entityId == nil)
    }

    private var title: String {
        if let name = entry.result?.name { return name }
        return entry.looked ? Copy.bookScanAddedNoDetail : Copy.bookScanLookingUp
    }

    private var detail: String {
        guard let result = entry.result else { return entry.isbn }
        return BooksRowText.found(authors: result.authors ?? [], existing: result.existing == true)
    }
}
