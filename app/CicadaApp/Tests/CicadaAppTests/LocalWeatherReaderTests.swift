import XCTest
@testable import CicadaApp

@MainActor
final class LocalWeatherReaderTests: XCTestCase {
    static let json = Data(#"{"current_units":{"wind_speed_10m":"km/h"},"current":{"weather_code":2,"wind_speed_10m":31}}"#.utf8)
    let zone = TimeZone(identifier: "Europe/London")!
    let point = GeoPoint(latitude: 51.5, longitude: -0.12)

    func testRequestSendsOnlyPublicCoordinatesAndConditions() throws {
        let request = try XCTUnwrap(LocalWeatherRequest.make(point: point))
        XCTAssertEqual(request.url?.scheme, "https")
        XCTAssertEqual(request.url?.host, "api.open-meteo.com")
        XCTAssertEqual(request.url?.path, "/v1/forecast")
        let query = try XCTUnwrap(URLComponents(url: XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(Set(query.map(\.name)), ["latitude", "longitude", "current", "wind_speed_unit", "forecast_days"])
        XCTAssertEqual(query.first { $0.name == "current" }?.value, "weather_code,wind_speed_10m")
        XCTAssertEqual(query.first { $0.name == "wind_speed_unit" }?.value, "kmh")
        XCTAssertEqual(request.timeoutInterval, 4)
        XCTAssertFalse(request.httpShouldHandleCookies)
        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(LocalWeatherRequest.make(point: .init(latitude: .nan, longitude: 0)))
        XCTAssertNil(LocalWeatherRequest.make(point: .init(latitude: 91, longitude: 0)))
    }

    func testOnlyVisibleLocalModeFetchesAndFailureIsThrottledToo() async {
        var now = Date(timeIntervalSince1970: 1000), calls = 0
        let reader = LocalWeatherReader(now: { now }, table: [zone.identifier: point], transport: { _ in
            calls += 1
            if calls == 1 { return Self.json }
            throw URLError(.notConnectedToInternet)
        })
        await reader.refreshIfNeeded(onScreen: false, mode: .localWeather, zone: zone)
        for mode in [SceneryMode.sleep, .choose] { await reader.refreshIfNeeded(onScreen: true, mode: mode, zone: zone) }
        XCTAssertEqual(calls, 0)
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 1); XCTAssertEqual(reader.base(for: zone.identifier), .windy)
        now = now.addingTimeInterval(1799)
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 1)
        now = now.addingTimeInterval(1)
        await reader.refreshIfNeeded(onScreen: false, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 1); XCTAssertNil(reader.base(for: zone.identifier), "expired readings cannot imply current weather")
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 2); XCTAssertNil(reader.base(for: zone.identifier))
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 2)
    }

    func testMissingZoneMalformedOversizedAndWrongUnitsFallBack() async {
        var calls = 0
        let missing = LocalWeatherReader(table: [:], transport: { _ in calls += 1; return Self.json })
        await missing.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 0); XCTAssertNil(missing.base(for: zone.identifier))
        let bad = [Data("bad".utf8), Data(repeating: 32, count: 65537),
                   Data(#"{"current_units":{"wind_speed_10m":"mph"},"current":{"weather_code":0,"wind_speed_10m":30}}"#.utf8),
                   Data(#"{"current_units":{"wind_speed_10m":"km/h"},"current":{"weather_code":444,"wind_speed_10m":0}}"#.utf8)]
        for bytes in bad {
            let reader = LocalWeatherReader(table: [zone.identifier: point], transport: { _ in bytes })
            await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
            XCTAssertNil(reader.base(for: zone.identifier))
        }
    }

    func testZoneSwitchNeverShowsAnotherCityAndDoesNotBypassRateLimit() async {
        var calls = 0
        let other = TimeZone(identifier: "Asia/Tokyo")!
        let reader = LocalWeatherReader(table: [zone.identifier: point, other.identifier: .init(latitude: 35, longitude: 139)],
                                        transport: { _ in calls += 1; return Self.json })
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: other)
        XCTAssertEqual(calls, 1)
        XCTAssertNil(reader.base(for: other.identifier))
        XCTAssertEqual(reader.base(for: zone.identifier), .windy)
    }

    func testCancellationAndConcurrentRequestsCannotPublishOrBypassThrottle() async {
        var pending: CheckedContinuation<Data, Never>?
        var calls = 0
        let started = expectation(description: "transport started")
        let reader = LocalWeatherReader(table: [zone.identifier: point], transport: { _ in
            calls += 1
            started.fulfill()
            return await withCheckedContinuation { pending = $0 }
        })
        let task = Task { await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone) }
        await fulfillment(of: [started], timeout: 1)
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 1)
        task.cancel() // leaving/occluding the room or selecting another source cancels this task
        pending?.resume(returning: Self.json)
        await task.value
        XCTAssertNil(reader.base(for: zone.identifier))
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 1)
    }

    func testTransportConfigurationHasNoPersistentStateOrCredentials() {
        let config = LocalWeatherTransport.configuration()
        XCTAssertNil(config.httpCookieStorage)
        XCTAssertNil(config.urlCredentialStorage)
        XCTAssertNil(config.urlCache)
        XCTAssertFalse(config.httpShouldSetCookies)
        XCTAssertEqual(config.timeoutIntervalForRequest, 4)
        XCTAssertEqual(config.timeoutIntervalForResource, 4)
    }

    func testStreamingTransportAcceptsExactly64KiBAndRejectsOversizeAndRefusals() async throws {
        let request = try XCTUnwrap(LocalWeatherRequest.make(point: point))
        let config = LocalWeatherTransport.configuration()
        config.protocolClasses = [WeatherProtocol.self] // intercept every URL; no real network
        defer { WeatherProtocol.handler = nil }
        for (count, status, headers, accepted) in [
            (65536, 200, ["Content-Type": "application/json"], true),
            (65537, 200, ["Content-Type": "application/json"], false),
            (1, 200, ["Content-Type": "application/json", "Content-Length": "65537"], false),
            (1, 403, ["Content-Type": "application/json"], false),
            (1, 429, ["Content-Type": "application/json"], false),
            (1, 302, ["Location": "https://example.com/", "Content-Type": "application/json"], false),
            (1, 200, ["Content-Type": "text/html"], false),
        ] {
            var calls = 0
            WeatherProtocol.handler = { request in
                calls += 1
                return (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!,
                        Data(repeating: 32, count: count))
            }
            do {
                let result = try await LocalWeatherTransport.load(request, configuration: config)
                XCTAssertTrue(accepted, "\(count) bytes, status \(status)")
                XCTAssertEqual(result.count, count)
            } catch { XCTAssertFalse(accepted, "\(error)") }
            XCTAssertEqual(calls, 1, "a refusal is never retried")
        }
        for url in ["http://api.open-meteo.com/v1/forecast", "https://example.com/v1/forecast", "https://api.open-meteo.com/other"] {
            WeatherProtocol.handler = { _ in XCTFail("invalid endpoint must be refused before transport"); throw URLError(.badURL) }
            do { _ = try await LocalWeatherTransport.load(URLRequest(url: URL(string: url)!), configuration: config); XCTFail("refuse endpoint") }
            catch { }
        }
    }

    func testRedirectPolicyNeverFollowsEvenTheSameHost() throws {
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let request = try XCTUnwrap(LocalWeatherRequest.make(point: point))
        let task = session.dataTask(with: request) // never resumed
        let response = try XCTUnwrap(HTTPURLResponse(url: XCTUnwrap(request.url), statusCode: 302, httpVersion: nil, headerFields: nil))
        var called = false
        LocalWeatherTransport.Policy().urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: request) {
            called = true; XCTAssertNil($0)
        }
        XCTAssertTrue(called)
    }
}

private final class WeatherProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (response, data) = try Self.handler!(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
