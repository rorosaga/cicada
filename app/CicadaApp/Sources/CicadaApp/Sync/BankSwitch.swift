import Foundation

/// G183(d) — one bank switch in flight: the operation's generation and its target. `Store.activateBank` is the only
/// door (the switcher, the find palette and the intake card all reach it through `BanksViewModel.activate`).
struct BankSwitch: Equatable {
    let generation: Int
    let target: String
}

extension Store {
    /// Switch the active bank as ONE serialized transition (G183(d), review findings 1–2).
    ///
    /// The server moves its active bank before it answers `POST /banks/{name}/activate` (and before its migrations
    /// run), so between the POST and the Store's own move the two disagree. The transition therefore:
    /// 1. reserves itself (`bankSwitch`, with a fresh generation) before its first await — a second switch from any
    ///    door is refused, never interleaved;
    /// 2. sends the old bank's held answer and waits for any answer already on the wire (R-DI3), so they land in the
    ///    bank they were made in;
    /// 3. posts the switch; while it waits every bank-scoped write is refused (`refusesWriteWhileSwitching`) —
    ///    refused rather than queued, because a write replayed afterwards would land in the new bank, and the old one
    ///    can no longer be reached;
    /// 4. on success moves to the bank the server's answer names (its roster), unless `refresh`'s fan-out saw the
    ///    server move somewhere else meanwhile — then the server's roster decides, never this older answer — and
    ///    reconciles the roster before releasing writes; the other domains reconcile after.
    /// A refusal changes nothing and toasts the server's sentence (`BankSwitchFailure`).
    @discardableResult
    func activateBank(_ name: String) async -> Bool {
        guard bankSwitch == nil else {
            toast = Copy.switchingMemory
            return false
        }
        bankSwitchGeneration &+= 1
        let operation = BankSwitch(generation: bankSwitchGeneration, target: name)
        bankSwitch = operation
        bankSeenDuringSwitch = nil
        defer { releaseBankSwitch(operation) }

        await flushHeld(duringSwitch: true)
        while !sendingInboxIds.isEmpty && !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(20))
        }

        let roster: BanksResponse?
        do {
            roster = try await api.activateBank(name: name)
        } catch {
            if !(SyncCancellation.isCancellation(error) || Task.isCancelled) { toast = BankSwitchFailure.message(error) }
            Self.logger.debug("bank switch failed: \(String(describing: error))")
            // The server's word on where it is — its own fan-out moves the Store if a refusal still moved it.
            await refresh([.banks])
            return false
        }

        if let seen = bankSeenDuringSwitch, seen != name {
            // The server moved past this switch while it was answered: never put this older answer back on screen.
            await refresh([.banks])
        } else {
            let active = roster?.active.flatMap { $0.isEmpty ? nil : $0 } ?? name
            if bank != active {
                bank = active
                await hydrate(bank: active)
            }
            if let roster {
                banks.value = roster
            } else if let current = banks.value {
                banks.value = BanksResponse(banks: current.banks.map { $0.settingActive($0.name == active) },
                                            active: active)
            }
            await refresh([.banks])
        }
        releaseBankSwitch(operation)
        // Writes go again: the roster is the server's and the bank's snapshots are its own (from cache, then below).
        await refresh(Set(SyncDomain.allCases).subtracting([.banks]))
        return true
    }

    /// Only the switch that reserved the marker clears it.
    private func releaseBankSwitch(_ operation: BankSwitch) {
        if bankSwitch == operation { bankSwitch = nil }
    }

    /// While a bank switch is in flight a bank-scoped write is not sent: it says so and answers true.
    func refusesWriteWhileSwitching() -> Bool {
        guard bankSwitch != nil else { return false }
        toast = Copy.switchingMemory
        return true
    }
}
