import AppKit
import Foundation
import Network
import dnssd

/// G132 ruling 51f, slice 1 — the app's side of the home-network door (network.md, "Discovery on the LAN"): Bonjour,
/// the network hints and the Local Network ask. The backend is a launchd agent, so its own Bonjour would raise the
/// alert under no app's name (TN3179); the app advertises the door's port, browses for this memory's other devices and
/// posts what it resolved (`POST /sync/discovered`), and tells the backend when the network changed or the app came
/// back (`POST /sync/network`).
///
/// **Nothing asks unasked (owner D4).** Every Bonjour call here runs only once the person answered the Local Network
/// prompt their own first share or add-device click raised (`ask()`): until then `LocalNetworkMemory` reads `notYet`
/// and nothing is advertised, browsed or probed. A refused answer is looked at again (silently: macOS never asks
/// twice) when the app comes back to the front, so turning it on in System Settings is picked up.
///
/// Advertising goes through `DNSServiceRegister` rather than an `NWListener`: a listener can advertise only a port it
/// holds itself, and the door's port is the backend's. Resolving a found instance goes through `DNSServiceResolve` and
/// `DNSServiceGetAddrInfo` — never a connection to it, which would spend the door's per-source handshake budget.
@MainActor
final class LanDiscovery {
    static let shared = LanDiscovery()

    private let memory: LocalNetworkMemory
    private var plan: DiscoveryPlan?
    private var browser: NWBrowser?
    private var browsedType: String?
    private var advert: DNSServiceRef?
    private var advertKey: String?
    /// The name mDNS gave this computer's own advertisement (a conflict renames it), so a browse skips itself.
    fileprivate var ownName: String?
    private var resolvers: [String: Resolver] = [:]
    fileprivate var resolved: [String: [(host: String, port: Int)]] = [:]
    private var lastPosted: (doors: [FoundDoor], at: Date)?
    private var postTask: Task<Void, Never>?
    private var monitor: NWPathMonitor?
    private var sawFirstPath = false
    private var changeTask: Task<Void, Never>?
    private var gate = NetworkHintGate()
    private var recheck = LocalNetworkRecheckGate()
    private var loop: Task<Void, Never>?

    init(memory: LocalNetworkMemory = LocalNetworkMemory()) {
        self.memory = memory
    }

    var state: MacPermissionState { memory.state }

    // MARK: Lifecycle

    /// At launch: the path monitor (it needs no permission), and Bonjour only if the person already allowed it.
    func start() {
        guard monitor == nil else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] _ in
            Task { @MainActor in self?.pathChanged() }
        }
        monitor.start(queue: .main)
        self.monitor = monitor
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: .seconds(CicadaTiming.discoveryRefresh))
            }
        }
    }

    /// The app is in front again: the backend tries every earlier route now; a refused answer is looked at again.
    func appBecameActive() {
        Task {
            // Review of #573: at most one silent re-check per window, never two at once, and only after the person's
            // own Allow click asked once — a probe after macOS forgot the answer could otherwise prompt unasked.
            let now = Date()
            if recheck.due(state: memory.state, askedBefore: memory.askedBefore, now: now) {
                recheck.started(at: now)
                let fresh = await probe(limit: CicadaTiming.localNetworkRecheck)
                recheck.finished()
                if let fresh, fresh != .denied {
                    memory.note(fresh)
                    await postAllowed()
                }
            }
            await refresh()
            await hint(.returned)
        }
    }

    // MARK: The ask (the person's click only)

    /// Raises macOS's Local Network prompt — the person's own Allow click in the first-share step — and waits for the
    /// answer: the app's throwaway instance seen in its own browse is a yes; a browse refused by policy that never saw
    /// it is a no. Then the backend is told (`lanAllowed`), so the door may bind this network.
    func ask() async {
        memory.noteAsked()
        let answer = await probe(limit: CicadaTiming.localNetworkAskLimit)
        if let answer { memory.note(answer) }
        await postAllowed()
        await refresh()
    }

    /// The person went through the step without allowing (or the answer has not come): the door stays on loopback.
    func stepDone() async {
        await postAllowed()
        await refresh()
    }

    private func postAllowed() async {
        _ = try? await APIClient.shared.postDiscovered(doors: [], lanAllowed: memory.state == .granted)
    }

    private func probe(limit: TimeInterval) async -> MacPermissionState? {
        let probe = SelfProbe()
        probe.start()
        let deadline = Date().addingTimeInterval(limit)
        while Date() < deadline, !probe.foundSelf {
            try? await Task.sleep(for: .seconds(CicadaTiming.localNetworkProbeStep))
        }
        probe.stop()
        return LocalNetworkVerdict.state(foundSelf: probe.foundSelf, policyDenied: probe.policyDenied, finished: true)
    }

    // MARK: Discovery

    /// Read the plan and match Bonjour to it: nothing while the memory is not shared or the person has not allowed it.
    func refresh() async {
        guard memory.state == .granted, let plan = try? await APIClient.shared.fetchDiscovery() else {
            stopDiscovery()
            plan = nil
            return
        }
        self.plan = plan
        advertise(plan.advertise, type: plan.type)
        if browser == nil || browsedType != plan.type {   // the door opened or closed: its type changed with it
            browser?.cancel()
            browser = nil
            browse(type: plan.type)
        }
        schedulePost()
    }

    private func stopDiscovery() {
        browser?.cancel()
        browser = nil
        if let advert { DNSServiceRefDeallocate(advert) }
        advert = nil
        advertKey = nil
        ownName = nil
        resolvers.values.forEach { $0.stop() }
        resolvers = [:]
        resolved = [:]
    }

    private func advertise(_ what: DiscoveryPlan.Advertise?, type: String) {
        let key = what.map { "\($0.name)|\($0.port)|\(type)" }
        guard key != advertKey else { return }
        if let advert { DNSServiceRefDeallocate(advert) }
        advert = nil
        ownName = nil
        advertKey = key
        guard let what, let port = UInt16(exactly: what.port) else { return }
        var ref: DNSServiceRef?
        let context = Unmanaged.passUnretained(self).toOpaque()
        let err = DNSServiceRegister(&ref, 0, 0, what.name, type, nil, nil, port.bigEndian, 0, nil,
                                     { _, _, error, name, _, _, context in
            guard error == kDNSServiceErr_NoError, let name, let context else { return }
            let me = Unmanaged<LanDiscovery>.fromOpaque(context).takeUnretainedValue()
            let given = String(cString: name)
            MainActor.assumeIsolated { me.ownName = given }
        }, context)
        guard err == kDNSServiceErr_NoError, let ref else { return }
        DNSServiceSetDispatchQueue(ref, .main)
        advert = ref
    }

    private func browse(type: String) {
        browsedType = type
        let browser = NWBrowser(for: .bonjour(type: type, domain: nil), using: LanRules.isUDP(type) ? .udp : .tcp)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in self?.found(results) }
        }
        browser.stateUpdateHandler = { [weak self] state in
            // A refusal in System Settings after it was allowed: remembered, the backend told, nothing browsed.
            if case .waiting(let error) = state, case .dns(let code) = error, code == kDNSServiceErr_PolicyDenied {
                Task { @MainActor in
                    guard let self else { return }
                    self.memory.note(.denied)
                    self.stopDiscovery()
                    await self.postAllowed()
                }
            }
        }
        browser.start(queue: .main)
        self.browser = browser
    }

    private func found(_ results: Set<NWBrowser.Result>) {
        guard let plan else { return }
        var seen = Set<String>()
        for result in results {
            guard case let .service(name, type, domain, interface) = result.endpoint,
                  LanRules.matches(name, instance: plan.browse), name != ownName else { continue }
            let key = "\(name)|\(interface?.index ?? 0)"
            seen.insert(key)
            guard resolvers[key] == nil else { continue }
            let resolver = Resolver(key: key, owner: self)
            resolvers[key] = resolver
            resolver.start(name: name, type: type, domain: domain, interface: UInt32(interface?.index ?? 0))
        }
        for gone in resolvers.keys where !seen.contains(gone) {
            resolvers[gone]?.stop()
            resolvers[gone] = nil
            resolved[gone] = nil
        }
        schedulePost()
    }

    fileprivate func addressesChanged() { schedulePost() }

    /// Post the found doors once they settle, when the set changed or `discoveryRepost` has passed.
    private func schedulePost() {
        postTask?.cancel()
        postTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(CicadaTiming.discoverySettle))
            guard !Task.isCancelled, let self, let plan = self.plan else { return }
            let rows = self.resolved.flatMap { key, hits in
                hits.map { (name: String(key.split(separator: "|").first ?? ""), host: $0.host, port: $0.port) }
            }
            let doors = LanRules.doors(rows, instance: plan.browse)
            let now = Date()
            if let last = self.lastPosted, last.doors == doors,
               now.timeIntervalSince(last.at) < CicadaTiming.discoveryRepost { return }
            guard !doors.isEmpty || self.lastPosted.map({ !$0.doors.isEmpty }) == true else { return }
            self.lastPosted = (doors, now)
            _ = try? await APIClient.shared.postDiscovered(doors: doors, lanAllowed: true)
        }
    }

    // MARK: Network hints

    private func pathChanged() {
        guard sawFirstPath else {
            sawFirstPath = true
            return
        }
        changeTask?.cancel()
        changeTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(CicadaTiming.networkChangeSettle))
            guard !Task.isCancelled, let self else { return }
            await self.hint(.changed)
            await self.refresh()
        }
    }

    /// `POST /sync/network` — only while this memory is shared or this computer keeps a copy: the plan says so when
    /// Bonjour runs; otherwise one read of it (a copy reached only over a tailnet still wants the hint).
    private func hint(_ event: NetworkHintGate.Event) async {
        let now = Date()
        guard gate.due(event, now: now) else { return }
        gate.sent(event, at: now)      // also bounds the plan read below to one per window
        if plan == nil, (try? await APIClient.shared.fetchDiscovery()) == nil { return }
        _ = try? await APIClient.shared.postNetwork(event: event.rawValue,
                                                    lanAllowed: memory.asked ? memory.state == .granted : nil)
    }

    // MARK: The macOS firewall

    /// Whether the application firewall is on (`socketfilterfw --getglobalstate`, read only, no prompt): its question
    /// about incoming connections comes once the door binds this network, so the step says so only then.
    nonisolated static func firewallOn() async -> Bool {
        await Task.detached(priority: .utility) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/libexec/ApplicationFirewall/socketfilterfw")
            process.arguments = ["--getglobalstate"]
            let out = Pipe()
            process.standardOutput = out
            process.standardError = FileHandle.nullDevice
            do { try process.run() } catch { return false }
            let killer = DispatchWorkItem { if process.isRunning { process.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + CicadaTiming.firewallReadLimit, execute: killer)
            let data = out.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            killer.cancel()
            return (String(data: data, encoding: .utf8) ?? "").lowercased().contains("enabled")
        }.value
    }
}

/// One found instance resolved to its addresses: `DNSServiceResolve` for the host and port, then
/// `DNSServiceGetAddrInfo` for the host's addresses. Lives while the instance is in the browse.
@MainActor
private final class Resolver {
    let key: String
    weak var owner: LanDiscovery?
    private var resolveRef: DNSServiceRef?
    private var addrRef: DNSServiceRef?
    fileprivate var port = 0

    init(key: String, owner: LanDiscovery) {
        self.key = key
        self.owner = owner
    }

    func start(name: String, type: String, domain: String, interface: UInt32) {
        var ref: DNSServiceRef?
        let context = Unmanaged.passUnretained(self).toOpaque()
        let err = DNSServiceResolve(&ref, 0, interface, name, type, domain,
                                    { _, _, interface, error, _, host, port, _, _, context in
            guard error == kDNSServiceErr_NoError, let host, let context else { return }
            let me = Unmanaged<Resolver>.fromOpaque(context).takeUnretainedValue()
            let target = String(cString: host)
            let number = Int(UInt16(bigEndian: port))
            MainActor.assumeIsolated { me.addresses(of: target, port: number, interface: interface) }
        }, context)
        guard err == kDNSServiceErr_NoError, let ref else { return }
        DNSServiceSetDispatchQueue(ref, .main)
        resolveRef = ref
    }

    private func addresses(of host: String, port: Int, interface: UInt32) {
        self.port = port
        if let addrRef { DNSServiceRefDeallocate(addrRef) }
        addrRef = nil
        owner?.resolved[key] = []
        var ref: DNSServiceRef?
        let context = Unmanaged.passUnretained(self).toOpaque()
        let protocols = DNSServiceProtocol(kDNSServiceProtocol_IPv4 | kDNSServiceProtocol_IPv6)
        let err = DNSServiceGetAddrInfo(&ref, 0, interface, protocols, host,
                                        { _, flags, _, error, _, address, _, context in
            guard error == kDNSServiceErr_NoError, flags & DNSServiceFlags(kDNSServiceFlagsAdd) != 0,
                  let address, let context else { return }
            let me = Unmanaged<Resolver>.fromOpaque(context).takeUnretainedValue()
            guard let text = Resolver.text(address) else { return }
            MainActor.assumeIsolated { me.add(text) }
        }, context)
        guard err == kDNSServiceErr_NoError, let ref else { return }
        DNSServiceSetDispatchQueue(ref, .main)
        addrRef = ref
    }

    private func add(_ host: String) {
        guard let owner else { return }
        var hits = owner.resolved[key] ?? []
        guard !hits.contains(where: { $0.host == host }) else { return }
        hits.append((host, port))
        owner.resolved[key] = hits
        owner.addressesChanged()
    }

    nonisolated static func text(_ address: UnsafePointer<sockaddr>) -> String? {
        var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        let length = socklen_t(address.pointee.sa_family == AF_INET6 ? MemoryLayout<sockaddr_in6>.size
                                                                     : MemoryLayout<sockaddr_in>.size)
        guard getnameinfo(address, length, &buffer, socklen_t(buffer.count), nil, 0, NI_NUMERICHOST) == 0 else {
            return nil
        }
        return String(cString: buffer)
    }

    func stop() {
        if let resolveRef { DNSServiceRefDeallocate(resolveRef) }
        if let addrRef { DNSServiceRefDeallocate(addrRef) }
        resolveRef = nil
        addrRef = nil
    }
}

/// The ask's own check: a throwaway instance (`cicada-probe-<random>`, port 9, no socket opened — so no firewall
/// question) and a browse that looks for it. Torn down as soon as the answer is known or the wait ends.
@MainActor
private final class SelfProbe {
    private(set) var foundSelf = false
    private(set) var policyDenied = false
    private let name = "cicada-probe-" + String(UInt32.random(in: .min ... .max), radix: 16)
    private var ref: DNSServiceRef?
    private var browser: NWBrowser?

    func start() {
        var ref: DNSServiceRef?
        let port = UInt16(9).bigEndian
        if DNSServiceRegister(&ref, 0, 0, name, LanRules.serviceType, nil, nil, port, 0, nil, nil, nil)
            == kDNSServiceErr_NoError, let ref {
            DNSServiceSetDispatchQueue(ref, .main)
            self.ref = ref
        }
        let browser = NWBrowser(for: .bonjour(type: LanRules.serviceType, domain: nil), using: .udp)
        let wanted = name
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let hit = results.contains { if case let .service(n, _, _, _) = $0.endpoint { n == wanted } else { false } }
            if hit { Task { @MainActor in self?.foundSelf = true } }
        }
        browser.stateUpdateHandler = { [weak self] state in
            if case .waiting(let error) = state, case .dns(let code) = error, code == kDNSServiceErr_PolicyDenied {
                Task { @MainActor in self?.policyDenied = true }
            }
        }
        browser.start(queue: .main)
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
        if let ref { DNSServiceRefDeallocate(ref) }
        ref = nil
    }
}
