import Foundation
import Observation

// G132 phase 3b — the relay (off by default) and pairing a computer through it. None of this is a Store domain: the
// relay setting and a pairing live outside every bank (`$CICADA_HOME/sync`), so they are read on demand and kept in
// memory while Settings → Devices is open.

/// `GET /sync/relay`.
struct RelaySetting: Decodable, Equatable, Sendable {
    let url: String?
    let on: Bool
    let text: String
}

/// The QR's payload, v2 (`sync_relay_pairing.qr_payload`): the code, the relay, a random slot and the home's public
/// keys, plus the home's direct address when it has one. Encoded with sorted keys so one code always draws one QR.
struct RelayQR: Codable, Equatable, Sendable {
    struct HomeKeys: Codable, Equatable, Sendable {
        let ed: String
        let x: String
    }

    let v: Int
    let code: String
    let relay: String
    let slot: String
    let home: HomeKeys
    var url: String? = nil

    var json: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return (try? encoder.encode(self)).flatMap { String(data: $0, encoding: .utf8) } ?? code
    }
}

/// One "add a computer" on the home's screen (`/devices/pairing/relay/{id}`).
struct RelaySession: Decodable, Equatable, Sendable {
    let id: String
    let state: String          // waiting | confirm | done | void | cancelled | expired
    var name: String? = nil
    var sas: String? = nil
    var typed: Bool = false
    var text: String? = nil

    enum CodingKeys: String, CodingKey { case id, state, name, sas, typed, text }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        state = (try? c.decode(String.self, forKey: .state)) ?? "waiting"
        name = try? c.decodeIfPresent(String.self, forKey: .name)
        sas = try? c.decodeIfPresent(String.self, forKey: .sas)
        typed = (try? c.decodeIfPresent(Bool.self, forKey: .typed)) ?? false
        text = try? c.decodeIfPresent(String.self, forKey: .text)
    }
}

struct RelayPairingCreated: Decodable, Sendable {
    let session: RelaySession
    let code: String
    let qr: RelayQR
}

struct RelaySessionAnswer: Decodable, Sendable { let session: RelaySession }

/// The new computer's side (`/sync/relay/join`).
struct RelayJoinState: Decodable, Equatable, Sendable {
    let state: String?         // connecting | confirm | waiting | done | void | failed | expired
    var sas: String? = nil
    var typed: Bool = false
    var text: String? = nil

    enum CodingKeys: String, CodingKey { case state, sas, typed, text }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try? c.decodeIfPresent(String.self, forKey: .state)
        sas = try? c.decodeIfPresent(String.self, forKey: .sas)
        typed = (try? c.decodeIfPresent(Bool.self, forKey: .typed)) ?? false
        text = try? c.decodeIfPresent(String.self, forKey: .text)
    }
}

/// The pure rules the screens follow (tested).
enum RelayRules {
    /// The relay address rule (`sync_transport.check_relay_url`): wss://, or ws:// to this computer only.
    static func address(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        guard let url = URL(string: trimmed), let host = url.host, !host.isEmpty, url.user == nil,
              url.password == nil, url.query == nil, url.fragment == nil else { return nil }
        if url.scheme == "wss" { return trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed }
        if url.scheme == "ws", ["127.0.0.1", "localhost", "::1"].contains(host) { return trimmed }
        return nil
    }

    /// The six digits, spaced as both screens show them: "123 456".
    static func digits(_ sas: String?) -> String? {
        guard let sas else { return nil }
        let only = sas.filter(\.isNumber)
        guard only.count == 6 else { return nil }
        return "\(only.prefix(3)) \(only.suffix(3))"
    }

    /// A pairing state that is over: the screen stops polling.
    static func finished(_ state: String?) -> Bool {
        ["done", "void", "cancelled", "expired", "failed"].contains(state ?? "")
    }
}

/// The home's "Pair a computer through the relay" sheet: make a code, poll it, confirm what answered.
@Observable
@MainActor
final class RelayPairModel {
    var created: RelayPairingCreated?
    var session: RelaySession?
    var problem: String?
    var busy = false

    func start() async {
        problem = nil
        do {
            let made = try await APIClient.shared.createRelayPairing()
            created = made
            session = made.session
        } catch {
            problem = ConnectionModelText.detail(error)?.text ?? Copy.Relay.notReachable
        }
    }

    func poll() async {
        guard let id = created?.session.id else { return }
        while !Task.isCancelled, !RelayRules.finished(session?.state) {
            try? await Task.sleep(for: .seconds(1))
            guard !Task.isCancelled, let fresh = try? await APIClient.shared.relayPairing(id) else { continue }
            session = fresh
        }
    }

    func confirm() async {
        guard let id = created?.session.id else { return }
        busy = true
        defer { busy = false }
        if let fresh = try? await APIClient.shared.confirmRelayPairing(id) { session = fresh }
    }

    func cancel() async {
        guard let id = created?.session.id, !RelayRules.finished(session?.state) else { return }
        try? await APIClient.shared.cancelRelayPairing(id)
    }
}

/// Settings → Devices on a computer that is not sharing yet: the relay address, and "Join with a code".
@Observable
@MainActor
final class RelayModel {
    var setting: RelaySetting?
    var address = ""
    var code = ""
    var joinRelay = ""
    var join: RelayJoinState?
    var problem: String?
    var busy = false
    /// This computer keeps its own memory and shares nothing: it may join another's.
    var canJoin = false
    /// This computer shares its memory: it pairs others.
    var sharing = false

    /// Shown only on a computer that keeps its own memory or a copy — never while this app uses a server.
    var shown = false

    func refresh() async {
        if let fresh = try? await APIClient.shared.fetchRelay() {
            setting = fresh
            if address.isEmpty { address = fresh.url ?? "" }
        }
        if let replica = try? await APIClient.shared.fetchReplica() {
            shown = replica.mode != "client"
            let publish = replica.mode == "local" ? try? await APIClient.shared.fetchPublish() : nil
            sharing = publish?.publish ?? false
            canJoin = replica.mode == "local" && !sharing
        }
    }

    func save() async {
        problem = nil
        let trimmed = address.trimmingCharacters(in: .whitespaces)
        guard trimmed.isEmpty || RelayRules.address(trimmed) != nil else {
            problem = Copy.Relay.badAddress
            return
        }
        busy = true
        defer { busy = false }
        do {
            setting = try await APIClient.shared.setRelay(url: trimmed.isEmpty ? nil : trimmed)
        } catch {
            problem = ConnectionModelText.detail(error)?.text ?? Copy.Relay.badAddress
        }
    }

    func turnOff() async {
        address = ""
        await save()
    }

    func startJoin() async {
        problem = nil
        guard let relay = RelayRules.address(joinRelay) else {
            problem = Copy.Relay.badAddress
            return
        }
        busy = true
        defer { busy = false }
        do {
            join = try await APIClient.shared.joinOverRelay(code: code.trimmingCharacters(in: .whitespaces),
                                                           relay: relay)
        } catch {
            problem = ConnectionModelText.detail(error)?.text ?? Copy.Relay.joinFailed
        }
    }

    func pollJoin() async {
        while !Task.isCancelled, join != nil, !RelayRules.finished(join?.state) {
            try? await Task.sleep(for: .seconds(1))
            guard !Task.isCancelled, let fresh = try? await APIClient.shared.joinState() else { continue }
            join = fresh
        }
    }

    func confirmJoin() async {
        if let fresh = try? await APIClient.shared.confirmJoin() { join = fresh }
    }

    func cancelJoin() async {
        try? await APIClient.shared.cancelJoin()
        join = nil
    }
}
