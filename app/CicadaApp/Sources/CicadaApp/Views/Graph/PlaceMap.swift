import AppKit
import CryptoKit
import MapKit
import SwiftUI

// Ruling 48 part 6 (owner 2026-10-28: "the cool looking macos maps… its already inside the mac"; part B, 2026-10-29).
//
// A place page draws a STILL of native Apple Maps from coordinates the page stores — the page's pin bold, the places on
// the record within a few km as small pins — and a click opens the live, native map. Nothing here runs when the card
// opens: the card paints its placeholder first, `GET /entities/{id}/place` and the snapshot run in `.task`, the
// snapshot off the main thread (`MKMapSnapshotter`), cached in memory and under the app's Caches folder (outside every
// bank).
//
// Coordinates are stored once. A place with none is resolved by the Mac's own geocoder (`MKLocalSearch`, Apple's
// service: the name leaves the Mac to Apple, never to anyone else) on the person's first open — only when the backend
// says it is a public place (`place_coordinates.geocode_verdict`, nothing sent to decide it). A private place (a home,
// an address, the person's own thing) shows "Place on the map" and is looked up only on that click. No Location
// Services: nothing here asks where the Mac is, so nothing prompts.

/// The Mac's own geocoder, behind a seam so tests and screenshots never reach Apple.
protocol PlaceGeocoding: Sendable {
    /// The place's coordinate, nil when the geocoder found nothing; throws when it could not ask (offline).
    func locate(_ query: String) async throws -> CLLocationCoordinate2D?
}

struct MacPlaceGeocoder: PlaceGeocoding {
    func locate(_ query: String) async throws -> CLLocationCoordinate2D? {
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = query
        request.resultTypes = [.pointOfInterest, .address]
        do {
            let response = try await MKLocalSearch(request: request).start()
            guard let item = response.mapItems.first else { return nil }
            if #available(macOS 26.0, *) { return item.location.coordinate }
            return item.placemark.coordinate
        } catch let error as MKError where error.code == .placemarkNotFound {
            return nil
        }
    }
}

/// Everything the map reaches outside itself, so a test or a screenshot can run it on fixtures.
struct PlaceServices {
    var load: (String) async throws -> PlaceState
    var store: (String, Double?, Double?, String) async throws -> PlaceState
    var remove: (String) async throws -> PlaceState
    var unplaced: () async throws -> [UnplacedPlace]
    var geocoder: PlaceGeocoding
    var still: (PlaceStill.Request) async -> NSImage?

    static let live = PlaceServices(
        load: { try await APIClient.shared.fetchPlace(id: $0) },
        store: { try await APIClient.shared.storeCoordinates(id: $0, lat: $1, lon: $2, by: $3) },
        remove: { try await APIClient.shared.removeCoordinates(id: $0) },
        unplaced: { try await APIClient.shared.fetchUnplacedPlaces(limit: PlaceBackfill.perSession) },
        geocoder: MacPlaceGeocoder(),
        still: { await PlaceStill.image(for: $0) })
}

// MARK: - The still

/// A muted still of the native map with the page's pin bold and its neighbours small (mock 03).
enum PlaceStill {
    struct Pin: Equatable, Hashable {
        var name: String
        var lat: Double
        var lon: Double
    }

    struct Request: Equatable, Hashable {
        var center: Pin
        var nearby: [Pin]
        var width: Int
        var height: Int
        var dark: Bool

        /// The span that shows every neighbour with a margin, never tighter than a neighbourhood.
        var span: MKCoordinateSpan {
            let lats = nearby.map { abs($0.lat - center.lat) }, lons = nearby.map { abs($0.lon - center.lon) }
            return MKCoordinateSpan(latitudeDelta: max(0.012, (lats.max() ?? 0) * 2.6),
                                    longitudeDelta: max(0.012, (lons.max() ?? 0) * 2.6))
        }

        var cacheKey: String {
            let pins = ([center] + nearby).map { "\($0.name)|\($0.lat)|\($0.lon)" }.joined(separator: ";")
            return "still-1#\(pins)#\(width)x\(height)#\(dark ? "d" : "l")"   // bump the head when the drawing changes
        }
    }

    @MainActor private static var memory: [String: NSImage] = [:]

    private static func cacheURL(_ key: String) -> URL? {
        guard let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else { return nil }
        let digest = SHA256.hash(data: Data(key.utf8)).prefix(12).map { String(format: "%02x", $0) }.joined()
        return base.appendingPathComponent("Cicada/place-stills/\(digest).png")
    }

    /// The still for a request: memory, then the Caches folder, then one `MKMapSnapshotter` run (off the main thread).
    static func image(for request: Request) async -> NSImage? {
        let key = request.cacheKey
        if let hit = await MainActor.run(body: { memory[key] }) { return hit }
        if let url = cacheURL(key), let data = try? Data(contentsOf: url), let image = NSImage(data: data) {
            await MainActor.run { memory[key] = image }
            return image
        }
        guard let image = await snapshot(request) else { return nil }
        await MainActor.run { memory[key] = image }
        if let url = cacheURL(key), let tiff = image.tiffRepresentation,
           let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? png.write(to: url, options: .atomic)
        }
        return image
    }

    private static func snapshot(_ request: Request) async -> NSImage? {
        let options = MKMapSnapshotter.Options()
        options.region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: request.center.lat,
                                                                           longitude: request.center.lon),
                                            span: request.span)
        options.size = NSSize(width: request.width, height: request.height)
        options.appearance = NSAppearance(named: request.dark ? .darkAqua : .aqua)
        // Muted (Apple's own muted emphasis): the record's places are the only pins and the loudest thing on the still.
        let configuration = MKStandardMapConfiguration(emphasisStyle: .muted)
        configuration.pointOfInterestFilter = .excludingAll
        options.preferredConfiguration = configuration
        guard let shot = try? await MKMapSnapshotter(options: options).start() else { return nil }
        return draw(shot, request)
    }

    /// The pins on the still: neighbours first (small, quiet), the page's own last (bold, labelled).
    private static func draw(_ shot: MKMapSnapshotter.Snapshot, _ request: Request) -> NSImage {
        let image = NSImage(size: shot.image.size)
        image.lockFocus()
        shot.image.draw(at: .zero, from: .zero, operation: .copy, fraction: 1)
        let ink = request.dark ? NSColor.white : NSColor(white: 0.08, alpha: 1)
        let paper = request.dark ? NSColor(white: 0.12, alpha: 0.92) : NSColor(white: 1, alpha: 0.92)
        func label(_ text: String, at p: NSPoint, size: CGFloat, weight: NSFont.Weight) {
            let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: size, weight: weight),
                                                        .foregroundColor: ink]
            let s = NSAttributedString(string: text, attributes: attrs)
            let r = NSRect(x: p.x, y: p.y - s.size().height / 2, width: s.size().width + 10, height: s.size().height + 4)
            paper.setFill()
            NSBezierPath(roundedRect: r.offsetBy(dx: -5, dy: -2), xRadius: 4, yRadius: 4).fill()
            s.draw(at: NSPoint(x: r.minX, y: r.minY))
        }
        func flipped(_ p: CGPoint) -> NSPoint { NSPoint(x: p.x, y: shot.image.size.height - p.y) }
        for pin in request.nearby {
            let p = flipped(shot.point(for: CLLocationCoordinate2D(latitude: pin.lat, longitude: pin.lon)))
            ink.withAlphaComponent(0.85).setFill()
            NSBezierPath(ovalIn: NSRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)).fill()
            label(pin.name, at: NSPoint(x: p.x + 9, y: p.y), size: 11, weight: .regular)
        }
        let c = flipped(shot.point(for: CLLocationCoordinate2D(latitude: request.center.lat,
                                                               longitude: request.center.lon)))
        paper.setFill()
        NSBezierPath(ovalIn: NSRect(x: c.x - 10, y: c.y - 10, width: 20, height: 20)).fill()
        ink.setFill()
        NSBezierPath(ovalIn: NSRect(x: c.x - 7, y: c.y - 7, width: 14, height: 14)).fill()
        label(request.center.name, at: NSPoint(x: c.x + 15, y: c.y), size: 12, weight: .semibold)
        image.unlockFocus()
        return image
    }
}

// MARK: - The background pass

/// Once a session, after a place page is placed: a few public places on the record resolved by the Mac's geocoder, a
/// second apart, so the nearby pins fill in. Public places only (`GET /places/unplaced`); never a private one.
@MainActor
enum PlaceBackfill {
    static let perSession = 5
    private static var ran = false

    static func runOnce(_ services: PlaceServices) {
        guard !ran else { return }
        ran = true
        Task {
            guard let todo = try? await services.unplaced() else { return }
            for place in todo.prefix(perSession) {
                try? await Task.sleep(for: .seconds(1.2))   // Apple's geocoder is rate-limited; a pass never hurries
                let found: CLLocationCoordinate2D?
                do { found = try await services.geocoder.locate(place.query) } catch { return }   // offline: next session
                if let c = found {
                    _ = try? await services.store(place.entityId, c.latitude, c.longitude, "geocoder")
                } else {
                    _ = try? await services.store(place.entityId, nil, nil, "none")
                }
            }
        }
    }

    static func resetForTests() { ran = false }
}

// MARK: - The view

/// What the map shows, decided from the page's served coordinates and `GET /place` — testable without a view.
enum PlacePhase: Equatable {
    case reading            // nothing stored yet and the place state not read: the quiet placeholder
    case placed(PageBlocks.Coordinates)
    case looking            // the geocoder is asked (automatic for a public place, or the person's click)
    case ask(reason: String) // a private place, or one taken back: "Place on the map"
    case notFound
    case failed

    static func initial(_ served: PageBlocks.Coordinates?) -> PlacePhase {
        served.map { .placed($0) } ?? .reading
    }
}

struct PlaceMap: View {
    let entity: Entity
    var services: PlaceServices = .live
    static let height: CGFloat = 220

    @State private var phase: PlacePhase = .reading
    @State private var nearby: [PlaceState.Nearby] = []
    @State private var still: NSImage?
    @State private var showLive = false
    @State private var stillWidth: CGFloat = 640
    @Environment(\.colorScheme) private var scheme

    private var served: PageBlocks.Coordinates? {
        if let c = entity.blocks?.coordinates { return c }
        return LocationHero.declaredCoordinate(from: entity.rawMarkdown).map {
            PageBlocks.Coordinates(lat: $0.latitude, lon: $0.longitude, label: entity.name, source: "page", by: nil)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            frame
            caption
        }
        .task(id: entity.id) { await read() }
        .task(id: stillRequest) { await drawStill() }
        .sheet(isPresented: $showLive) {
            if case .placed(let c) = phase {
                LivePlaceMap(name: entity.name, center: c, nearby: nearby) { showLive = false }
            }
        }
    }

    private var frame: some View {
        ZStack {
            CicadaTheme.surfaceHover.opacity(0.5)
            if let still {
                Image(nsImage: still).resizable().scaledToFill()
                    .accessibilityLabel("Map of \(entity.name)")
            } else {
                placeholder
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: Self.height)
        .background(GeometryReader { g in Color.clear.onAppear { stillWidth = g.size.width }
            .onChange(of: g.size.width) { _, w in stillWidth = w } })
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadius).stroke(CicadaTheme.border, lineWidth: 1))
        .overlay(alignment: .bottomTrailing) {
            if case .placed = phase {
                NeutralButton(title: Copy.Graph.openInMaps, size: .compact) { showLive = true }
                    .padding(CicadaTheme.spacingSM)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { if case .placed = phase { showLive = true } }
        .accessibilityIdentifier("place-map")
    }

    @ViewBuilder
    private var placeholder: some View {
        switch phase {
        case .ask:
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.placePrivate).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                NeutralButton(title: Copy.Graph.placeOnMap, size: .compact, help: Copy.Graph.placeOnMapHelp) {
                    Task { await locate(by: "person") }
                }
            }
        case .notFound:
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.placeNotFound).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                NeutralButton(title: Copy.Graph.placeOnMap, size: .compact, help: Copy.Graph.placeOnMapHelp) {
                    Task { await locate(by: "person") }
                }
            }
        case .looking:
            Text(Copy.Graph.placeLooking).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        default:
            Text(entity.name).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private var caption: some View {
        if case .placed = phase {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.placeCaption(nearby: nearby.count))
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                Spacer(minLength: 0)
                TextButton(title: Copy.Graph.removePin, help: Copy.Graph.removePinHelp, inline: true) {
                    Task { await takeBack() }
                }
            }
        }
    }

    private var stillRequest: PlaceStill.Request? {
        guard case .placed(let c) = phase else { return nil }
        let pins = nearby.map { PlaceStill.Pin(name: $0.name, lat: $0.lat, lon: $0.lon) }
        // Whole points, rounded to 40 pt steps, so a resize does not re-render on every pixel.
        let w = max(320, Int((stillWidth / 40).rounded()) * 40)
        return PlaceStill.Request(center: PlaceStill.Pin(name: entity.name, lat: c.lat, lon: c.lon), nearby: pins,
                                  width: w, height: Int(Self.height), dark: scheme == .dark)
    }

    private func drawStill() async {
        guard let request = stillRequest else { still = nil; return }
        let image = await services.still(request)
        guard !Task.isCancelled else { return }
        still = image
    }

    private func read() async {
        phase = PlacePhase.initial(served)
        nearby = []
        still = nil
        let id = entity.id
        guard let state = try? await services.load(id), id == entity.id else { return }
        apply(state)
        if state.coordinates == nil, let g = state.geocode {
            if g.allowed { await locate(by: "geocoder", query: g.query) } else { phase = .ask(reason: g.reason) }
        }
    }

    private func apply(_ state: PlaceState) {
        nearby = state.nearby
        if let c = state.coordinates { phase = .placed(c) }
    }

    private func locate(by: String, query: String? = nil) async {
        let id = entity.id
        phase = .looking
        do {
            if let c = try await services.geocoder.locate(query ?? entity.name) {
                let state = try await services.store(id, c.latitude, c.longitude, by)
                guard id == entity.id else { return }
                apply(state)
                PlaceBackfill.runOnce(services)
            } else {
                if by == "geocoder" { _ = try? await services.store(id, nil, nil, "none") }
                phase = .notFound
            }
        } catch {
            phase = by == "person" ? .failed : .ask(reason: "offline")
        }
    }

    private func takeBack() async {
        guard let state = try? await services.remove(entity.id) else { return }
        nearby = []
        still = nil
        phase = .ask(reason: state.geocode?.reason ?? "taken_back")
    }
}

/// The live, native map a click opens: pan and zoom, the page's pin and its neighbours, Open in Maps.
struct LivePlaceMap: View {
    let name: String
    let center: PageBlocks.Coordinates
    let nearby: [PlaceState.Nearby]
    let done: () -> Void

    private var coordinate: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude: center.lat, longitude: center.lon) }

    var body: some View {
        VStack(spacing: 0) {
            Map(initialPosition: .region(MKCoordinateRegion(center: coordinate,
                                                            span: MKCoordinateSpan(latitudeDelta: 0.03,
                                                                                   longitudeDelta: 0.03)))) {
                Marker(name, coordinate: coordinate)
                ForEach(nearby) { place in
                    Annotation(place.name, coordinate: CLLocationCoordinate2D(latitude: place.lat, longitude: place.lon)) {
                        Circle().fill(CicadaTheme.textPrimary).frame(width: 8, height: 8)
                    }
                }
            }
            .frame(minWidth: 640, minHeight: 440)
            HStack {
                Text(name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                NeutralButton(title: Copy.Graph.openInMaps, size: .compact) {
                    let q = name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? name
                    if let url = URL(string: "https://maps.apple.com/?ll=\(center.lat),\(center.lon)&q=\(q)") {
                        NSWorkspace.shared.open(url)
                    }
                }
                NeutralButton(title: "Done", size: .compact, shortcut: .cancelAction, action: done)
            }
            .padding(CicadaTheme.spacingMD)
        }
    }
}
