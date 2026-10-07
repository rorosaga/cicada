import Foundation

/// G183(d) — one bank switch in flight: the operation's generation and its target (nil when the server picks it, as
/// leaving the demo does).
struct BankSwitch: Equatable {
    let generation: Int
    let target: String?
}

/// A second switch asked for while one waits on the server.
struct BankSwitchInFlight: LocalizedError {
    var errorDescription: String? { Copy.switchingMemory }
}

extension Store {
    /// Switch the active bank (the switcher, the find palette, the intake card — all through
    /// `BanksViewModel.activate`). Toasts a refusal; true when the switch landed.
    @discardableResult
    func activateBank(_ name: String) async -> Bool {
        do {
            _ = try await switchBank(to: name, post: { [api] in try await api.activateBank(name: name) },
                                     roster: { $0 })
            return true
        } catch {
            if !(SyncCancellation.isCancellation(error) || Task.isCancelled) {
                toast = error is BankSwitchInFlight ? Copy.switchingMemory : BankSwitchFailure.message(error)
            }
            Self.logger.debug("bank switch failed: \(String(describing: error))")
            return false
        }
    }

    /// Every route that changes the active bank goes through this one serialized transition (G183(d)): a switch by
    /// name, entering the demo (`POST /banks/demo`) and leaving it (`POST /banks/leave-demo`).
    ///
    /// The server's bank check (`X-Cicada-Bank`, `BankScope`) is what keeps a write out of the wrong bank; this is the
    /// UX around it, so the app neither shows one bank while writing to another nor interleaves two switches:
    /// 1. it reserves itself (`bankSwitch`, a fresh generation) before its first await — a second switch from any
    ///    door throws `BankSwitchInFlight`, never interleaved;
    /// 2. it sends the old bank's held answer and waits for every answer already accepted (queued or on the wire), so
    ///    they land in the bank they were made in (R-DI3);
    /// 3. it posts; while it waits new writes are refused with "Switching memory — try again in a moment."
    ///    (`refusesWriteWhileSwitching`) — refused, not queued: a replay would land in the new bank;
    /// 4. on success it moves to the bank the server's answer names, unless `refresh`'s fan-out saw the server move
    ///    somewhere else meanwhile (then the server's roster decides, and this older answer is never shown); it
    ///    reconciles the roster, releases writes (only its own generation clears the marker), then the rest.
    /// A failure changes nothing and is thrown to the door, which says it its own way.
    func switchBank<R>(to target: String?, post: () async throws -> R,
                       roster: (R) -> BanksResponse?) async throws -> R {
        guard bankSwitch == nil else { throw BankSwitchInFlight() }
        bankSwitchGeneration &+= 1
        let operation = BankSwitch(generation: bankSwitchGeneration, target: target)
        bankSwitch = operation
        bankSeenDuringSwitch = nil
        defer { releaseBankSwitch(operation) }

        await flushHeld()
        while !sendingInboxIds.isEmpty && !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(20))
        }

        let answer: R
        do {
            answer = try await post()
        } catch {
            // The server's word on where it is — its own fan-out moves the Store if a refusal still moved it.
            await refresh([.banks])
            throw error
        }

        let returned = roster(answer)
        let landed = returned?.active.flatMap { $0.isEmpty ? nil : $0 } ?? target
        if let seen = bankSeenDuringSwitch, seen != landed {
            // The server moved past this switch while it was answered: never put this older answer back on screen.
            await refresh([.banks])
        } else if let landed {
            if bank != landed {
                bank = landed
                await hydrate(bank: landed)
            }
            if let returned {
                banks.value = returned
            } else if let current = banks.value {
                banks.value = BanksResponse(banks: current.banks.map { $0.settingActive($0.name == landed) },
                                            active: landed)
            }
            await refresh([.banks])
        } else {
            await refresh([.banks])
        }
        releaseBankSwitch(operation)
        // Writes go again: the roster is the server's and the bank's snapshots are its own (from cache, then below).
        await refresh(Set(SyncDomain.allCases).subtracting([.banks]))
        return answer
    }

    /// Only the switch that reserved the marker clears it.
    private func releaseBankSwitch(_ operation: BankSwitch) {
        if bankSwitch == operation { bankSwitch = nil }
    }

    /// While a bank switch is in flight a new bank-scoped write is not sent: it says so and answers true.
    func refusesWriteWhileSwitching() -> Bool {
        guard bankSwitch != nil else { return false }
        toast = Copy.switchingMemory
        return true
    }
}
