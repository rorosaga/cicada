import XCTest
import Darwin
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
        XCTAssertEqual(request.url?.absoluteString, "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current=weather_code,wind_speed_10m&wind_speed_unit=kmh&forecast_days=1")
        XCTAssertEqual(request.allHTTPHeaderFields, ["Accept": "application/json", "Accept-Language": "",
                                                    "Accept-Encoding": "identity", "User-Agent": "weather-reader"])
        XCTAssertFalse(request.httpShouldHandleCookies)
        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(LocalWeatherRequest.make(point: .init(latitude: .nan, longitude: 0)))
        XCTAssertNil(LocalWeatherRequest.make(point: .init(latitude: 91, longitude: 0)))
    }

    func testBackwardsClockIsDueAndTheNextAttemptRestartsTheThrottle() async {
        var now = Date(timeIntervalSince1970: 100_000), calls = 0
        let reader = LocalWeatherReader(now: { now }, table: [zone.identifier: point], transport: { _ in
            calls += 1; return Self.json
        })
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        now = now.addingTimeInterval(-86_400)
        XCTAssertNil(reader.base(for: zone.identifier))
        XCTAssertEqual(reader.delayUntilNextAttempt(), 0)
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(reader.base(for: zone.identifier), .windy)
        XCTAssertEqual(reader.delayUntilNextAttempt(), 1800)
    }

    func testExpiredReadingStaysDuringRefreshAndFailureClearsIt() async {
        var now = Date(timeIntervalSince1970: 100_000), calls = 0
        var pending: CheckedContinuation<Data, Error>?
        let started = expectation(description: "refresh started")
        let reader = LocalWeatherReader(now: { now }, table: [zone.identifier: point], transport: { _ in
            calls += 1
            if calls == 1 { return Self.json }
            started.fulfill()
            return try await withCheckedThrowingContinuation { pending = $0 }
        })
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        now = now.addingTimeInterval(86_400)
        XCTAssertNil(reader.base(for: zone.identifier), "hidden stale readings expire")
        XCTAssertEqual(reader.base(for: zone.identifier, refreshWhenVisible: true), .windy,
                       "the return-to-room body must not flash fallback before its task starts")
        let task = Task { await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone) }
        await fulfillment(of: [started], timeout: 1)
        XCTAssertEqual(reader.base(for: zone.identifier), .windy, "keep the room lit the same way while revalidating")
        XCTAssertNil(reader.base(for: "Asia/Tokyo"))
        pending?.resume(throwing: URLError(.notConnectedToInternet))
        await task.value
        XCTAssertNil(reader.base(for: zone.identifier))
        XCTAssertNil(reader.base(for: zone.identifier, refreshWhenVisible: true), "failure cannot stand in for current weather")
        XCTAssertEqual(calls, 2)
    }

    func testCancelledRevalidationExpiresAndCannotReturnAnotherCityOrBypassThrottle() async {
        var now = Date(timeIntervalSince1970: 100_000), calls = 0
        var pending: CheckedContinuation<Data, Never>?
        let started = expectation(description: "refresh started")
        let reader = LocalWeatherReader(now: { now }, table: [zone.identifier: point], transport: { _ in
            calls += 1
            if calls == 1 { return Self.json }
            started.fulfill()
            return await withCheckedContinuation { pending = $0 }
        })
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        now = now.addingTimeInterval(1800)
        let task = Task { await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone) }
        await fulfillment(of: [started], timeout: 1)
        XCTAssertEqual(reader.base(for: zone.identifier), .windy)
        XCTAssertNil(reader.base(for: "Asia/Tokyo", refreshWhenVisible: true))
        task.cancel(); pending?.resume(returning: Self.json); await task.value
        XCTAssertNil(reader.base(for: zone.identifier, refreshWhenVisible: true))
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        XCTAssertEqual(calls, 2)
    }

    func testAnotherCityInFlightCannotKeepAnExpiredReadingWhenItsRefreshCannotStart() async {
        var now = Date(timeIntervalSince1970: 100_000), calls = 0
        let other = TimeZone(identifier: "Asia/Tokyo")!
        var pending: CheckedContinuation<Data, Never>?
        let started = expectation(description: "other city's refresh started")
        let reader = LocalWeatherReader(now: { now }, table: [zone.identifier: point, other.identifier: point], transport: { _ in
            calls += 1
            if calls == 1 { return Self.json }
            started.fulfill()
            return await withCheckedContinuation { pending = $0 }
        })
        await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: zone)
        now = now.addingTimeInterval(1800)
        let task = Task { await reader.refreshIfNeeded(onScreen: true, mode: .localWeather, zone: other) }
        await fulfillment(of: [started], timeout: 1)
        now = now.addingTimeInterval(1800) // a forward clock adjustment during the request
        XCTAssertNil(reader.base(for: zone.identifier, refreshWhenVisible: true), "another in-flight city prevents a refresh")
        task.cancel(); pending?.resume(returning: Self.json); await task.value
        XCTAssertEqual(calls, 2)
    }

    func testTransportReceivesExactlyTheFixedHeadersAndPublicURL() async throws {
        let request = try XCTUnwrap(LocalWeatherRequest.make(point: point))
        let config = LocalWeatherTransport.configuration()
        config.protocolClasses = [WeatherProtocol.self]
        defer { WeatherProtocol.handler = nil }
        WeatherProtocol.handler = { outgoing in
            XCTAssertEqual(outgoing.url, request.url)
            XCTAssertEqual(outgoing.allHTTPHeaderFields, ["Accept": "application/json", "Accept-Language": "",
                                                         "Accept-Encoding": "identity", "User-Agent": "weather-reader"])
            XCTAssertFalse(outgoing.httpShouldHandleCookies)
            return (HTTPURLResponse(url: outgoing.url!, statusCode: 200, httpVersion: nil,
                                    headerFields: ["Content-Type": "application/json"])!, Self.json)
        }
        _ = try await LocalWeatherTransport.load(request, configuration: config)
    }

    /// URLProtocol cannot see headers that CFNetwork adds. Capture a real loopback request too.
    func testCFNetworkWireRequestContainsNoViewerLanguageCookiesOrIdentifiers() async throws {
        let listener = try WeatherWireListener()
        let capture = Task.detached { try listener.receive() }
        var request = try XCTUnwrap(LocalWeatherRequest.make(point: point))
        var local = try XCTUnwrap(URLComponents(url: XCTUnwrap(request.url), resolvingAgainstBaseURL: false))
        local.scheme = "http"; local.host = "127.0.0.1"; local.port = listener.port
        request.url = try XCTUnwrap(local.url) // only the destination changes; no public network request
        let session = URLSession(configuration: LocalWeatherTransport.configuration())
        defer { session.invalidateAndCancel() }
        _ = try await session.data(for: request)
        let lines = try await capture.value.components(separatedBy: "\r\n")
        XCTAssertEqual(lines.first, "GET /v1/forecast?latitude=51.5&longitude=-0.12&current=weather_code,wind_speed_10m&wind_speed_unit=kmh&forecast_days=1 HTTP/1.1")
        let headers = Dictionary(uniqueKeysWithValues: lines.dropFirst().filter { $0.contains(":") }.map { line in
            let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            return (parts[0].lowercased(), parts[1].trimmingCharacters(in: .whitespaces))
        })
        XCTAssertEqual(headers, ["host": "127.0.0.1:\(listener.port)", "connection": "keep-alive",
                                 "accept": "application/json", "accept-language": "", "accept-encoding": "identity",
                                 "user-agent": "weather-reader"])
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

private final class WeatherWireListener: @unchecked Sendable {
    let descriptor: Int32
    let port: Int
    init() throws {
        let socket = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard socket >= 0 else { throw POSIXError(.EIO) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socket, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard bound == 0, Darwin.listen(socket, 1) == 0 else { Darwin.close(socket); throw POSIXError(.EIO) }
        var size = socklen_t(MemoryLayout<sockaddr_in>.size)
        let named = withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socket, $0, &size) }
        }
        guard named == 0 else { Darwin.close(socket); throw POSIXError(.EIO) }
        descriptor = socket; port = Int(UInt16(bigEndian: address.sin_port))
    }
    deinit { Darwin.close(descriptor) }
    func receive() throws -> String {
        var ready = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
        guard Darwin.poll(&ready, 1, 5000) > 0 else { throw URLError(.timedOut) }
        let client = Darwin.accept(descriptor, nil, nil)
        guard client >= 0 else { throw POSIXError(.EIO) }
        defer { Darwin.close(client) }
        var noSignal: Int32 = 1
        setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        var bytes = Data(), buffer = [UInt8](repeating: 0, count: 4096)
        while !bytes.suffix(4).elementsEqual([13, 10, 13, 10]) {
            let count = Darwin.recv(client, &buffer, buffer.count, 0)
            guard count > 0, bytes.count + count <= 8192 else { throw URLError(.badServerResponse) }
            bytes.append(contentsOf: buffer.prefix(count))
        }
        let response = Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{}".utf8)
        let sent = response.withUnsafeBytes { Darwin.send(client, $0.baseAddress, $0.count, 0) }
        guard sent == response.count else { throw POSIXError(.EIO) }
        return String(decoding: bytes, as: UTF8.self)
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
