import Foundation
import Observation

struct WeatherWatchKey: Equatable {
    let onScreen: Bool
    let mode: SceneryMode
    let zone: String
}

enum LocalWeatherRequest {
    static let host = "api.open-meteo.com"
    static let timeout: TimeInterval = 4
    static let byteLimit = 64 * 1024
    static let interval: TimeInterval = 30 * 60

    static func make(point: GeoPoint) -> URLRequest? {
        guard point.latitude.isFinite, point.longitude.isFinite,
              (-90...90).contains(point.latitude), (-180...180).contains(point.longitude) else { return nil }
        var url = URLComponents()
        url.scheme = "https"; url.host = host; url.path = "/v1/forecast"
        url.queryItems = [
            .init(name: "latitude", value: String(point.latitude)),
            .init(name: "longitude", value: String(point.longitude)),
            .init(name: "current", value: "weather_code,wind_speed_10m"),
            .init(name: "wind_speed_unit", value: "kmh"),
            .init(name: "forecast_days", value: "1"),
        ]
        guard let endpoint = url.url else { return nil }
        var request = URLRequest(url: endpoint, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.httpShouldHandleCookies = false
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        // A constant header avoids the system's app/version/device User-Agent. No viewer identifier.
        request.setValue("weather-reader", forHTTPHeaderField: "User-Agent")
        return request
    }
}

/// No redirects, authentication, cookies, disk cache or credentials. The body is bounded while streaming.
enum LocalWeatherTransport {
    enum Failure: Error { case refused, tooLarge }
    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCredentialStorage = nil
        config.urlCache = nil
        config.timeoutIntervalForRequest = LocalWeatherRequest.timeout
        config.timeoutIntervalForResource = LocalWeatherRequest.timeout
        return config
    }

    static func load(_ request: URLRequest, configuration: URLSessionConfiguration = configuration()) async throws -> Data {
        guard request.url?.scheme == "https", request.url?.host == LocalWeatherRequest.host,
              request.url?.path == "/v1/forecast", request.url?.user == nil, request.url?.password == nil,
              request.url?.port == nil else { throw Failure.refused }
        let session = URLSession(configuration: configuration, delegate: Policy(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              http.url == request.url, http.mimeType == "application/json" else { throw Failure.refused }
        guard response.expectedContentLength <= LocalWeatherRequest.byteLimit else { throw Failure.tooLarge }
        var body = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard body.count < LocalWeatherRequest.byteLimit else { throw Failure.tooLarge }
            body.append(byte)
        }
        return body
    }

    final class Policy: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
        func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            // TLS uses the system trust evaluator; HTTP authentication never uses stored credentials.
            completionHandler(challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust
                              ? .performDefaultHandling : .cancelAuthenticationChallenge, nil)
        }
    }
}

/// Not a Store domain. Public conditions and attempt times exist only in process memory, never in a bank.
@MainActor @Observable
final class LocalWeatherReader {
    static let shared = LocalWeatherReader()
    private var cachedBase: WindowWeather?
    private var cachedZone: String?
    private var fetchedAt: Date?
    @ObservationIgnored private var attemptedAt: Date?
    @ObservationIgnored private var inFlight = false
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let table: [String: GeoPoint]
    @ObservationIgnored private let transport: (URLRequest) async throws -> Data

    init(now: @escaping () -> Date = Date.init, table: [String: GeoPoint] = TimeZoneCoordinates.bundled,
         transport: @escaping (URLRequest) async throws -> Data = { try await LocalWeatherTransport.load($0) }) {
        self.now = now; self.table = table; self.transport = transport
    }

    func base(for zone: String) -> WindowWeather? {
        guard zone == cachedZone, let fetchedAt, now().timeIntervalSince(fetchedAt) >= 0,
              now().timeIntervalSince(fetchedAt) < LocalWeatherRequest.interval else { return nil }
        return cachedBase
    }

    func delayUntilNextAttempt() -> TimeInterval {
        guard let attemptedAt else { return 0 }
        return max(0, LocalWeatherRequest.interval - now().timeIntervalSince(attemptedAt))
    }

    func refreshIfNeeded(onScreen: Bool, mode: SceneryMode, zone: TimeZone) async {
        guard onScreen, mode == .localWeather, !Task.isCancelled, !inFlight, delayUntilNextAttempt() <= 0,
              let point = TimeZoneCoordinates.point(for: zone.identifier, in: table),
              let request = LocalWeatherRequest.make(point: point) else { return }
        attemptedAt = now(); inFlight = true
        defer { inFlight = false }
        do {
            let data = try await transport(request)
            try Task.checkCancellation()
            guard data.count <= LocalWeatherRequest.byteLimit else { throw LocalWeatherTransport.Failure.tooLarge }
            struct Payload: Decodable {
                struct Current: Decodable { let weather_code: Int; let wind_speed_10m: Double }
                struct Units: Decodable { let wind_speed_10m: String }
                let current: Current
                let current_units: Units
            }
            let payload = try JSONDecoder().decode(Payload.self, from: data)
            guard payload.current_units.wind_speed_10m == "km/h",
                  let base = WeatherReading(code: payload.current.weather_code, windKmh: payload.current.wind_speed_10m).base
            else { throw LocalWeatherTransport.Failure.refused }
            cachedBase = base; cachedZone = zone.identifier; fetchedAt = now()
        } catch {
            if !Task.isCancelled { cachedBase = nil; cachedZone = nil; fetchedAt = nil }
        }
    }

    /// SwiftUI owns cancellation: leaving/occluding the room or choosing another source cancels both fetch and wait.
    func watch(onScreen: Bool, mode: SceneryMode, zone: TimeZone) async {
        guard onScreen, mode == .localWeather, let point = table[zone.identifier],
              LocalWeatherRequest.make(point: point) != nil else { return }
        while !Task.isCancelled {
            await refreshIfNeeded(onScreen: onScreen, mode: mode, zone: zone)
            do { try await Task.sleep(for: .seconds(max(1, delayUntilNextAttempt()))) }
            catch { return }
        }
    }
}
