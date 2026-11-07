import AppKit
import SwiftUI

/// The pure copy decisions, hoisted so they are testable without SwiftUI.
enum ConnectorSetupState {

    /// The one thing a not-connected panel offers (owner 2026-11-05: nothing is asked for a token, a key or a
    /// password): a browser sign-in, or, when the backend has none for it, nothing but a line.
    enum Action: Equatable {
        case none, connect, signInAgain
    }

    static func action(_ status: ConnectorStatus) -> Action {
        guard !status.connected, status.appSignIn == true else { return .none }
        return status.reconnect == true || status.how == "reconnect" ? .signInAgain : .connect
    }

    /// The panel's first line: "Connected", or, with no sign-in to offer, where the source comes in instead.
    static func stepLabel(_ status: ConnectorStatus) -> String? {
        if status.connected { return "Connected" }
        return action(status) == .none ? Copy.Connect.noSignIn : nil
    }

    /// Ruling 47 tier 2's words, said once and before anything is connected (owner 2026-11-03): what it reads.
    static func readsLine(_ status: ConnectorStatus) -> String? {
        guard let reads = status.reads, !reads.isEmpty else { return nil }
        return reads
    }

    /// What a "Sync now" press actually did — never a bare "done".
    static func syncSummary(_ result: ConnectorSyncResult) -> String {
        switch result.status {
        case "ok":
            let newPart = result.new == 0 ? "Nothing new" : "\(result.new) new"
            var summary = "\(newPart) · \(result.seen) seen"
            // M1 (final review): X's pay-per-use billing must reach this
            // summary too — every other connector's response always carries
            // a literal 0, so this only ever appends for X.
            if result.resourcesRead > 0 {
                summary += " · \(result.resourcesRead) reads billed"
            }
            return summary
        case "skipped":
            return "Skipped — \(result.reason ?? "nothing to do")"
        default:
            return "Sync failed — \(result.error ?? "unknown error")"
        }
    }
}

/// Guided credential entry + status for one direct-API connector (G71 §2).
struct ConnectorSetupPanel: View {
    let connectorId: String
    /// Non-empty for Reddit, whose GDPR export backfills past the API's
    /// ~1,000-item listing cap; empty for Pinterest.
    let vendors: [WalkthroughVendor]
    @Binding var vendor: WalkthroughVendor

    @Environment(Store.self) private var store

    @State private var status: ConnectorStatus?
    @State private var busy = false
    @State private var message: String?
    @State private var error: String?
    /// True from the moment `authorize()` hands off to the browser until a
    /// check lands `connected == true` (or the panel is torn down). Gates the
    /// "Check status" affordance (fix round 1, M1) — the OAuth flow used to
    /// dead-end here with no way to see the result short of backing out to
    /// the tile grid and reopening.
    @State private var awaitingAuthorization = false
    /// The bounded auto-poll `authorize()` starts. Stored so `onDisappear`
    /// can cancel it — the same discipline `AddSourceSheet.importTask` uses
    /// for H1, so an abandoned poll never keeps running (or writing into
    /// @State) after the panel leaves the view tree.
    @State private var pollTask: Task<Void, Never>?

    /// 3s between checks, for up to 2 minutes — long enough for a real
    /// browser round trip, bounded so a user who never finishes the OAuth
    /// screen doesn't leave a poll running forever.
    private static let pollIntervalNanoseconds: UInt64 = 3_000_000_000
    private static let maxPollAttempts = 40

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let status {
                if let label = ConnectorSetupState.stepLabel(status) {
                    Text(label)
                        .font(CicadaTheme.font(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                }

                if let detail = status.detail ?? status.lastError {
                    Text(detail)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(status.lastError == nil
                                         ? CicadaTheme.textSecondary : CicadaTheme.danger)
                }

                // Ruling 47 tier 2: what it reads is said in words before anything is connected, and stays said.
                if let reads = ConnectorSetupState.readsLine(status) {
                    Text(reads)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }

                if status.connected {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button("Refresh") { Task { await syncNow() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy)
                        Button("Disconnect", role: .destructive) { Task { await disconnect() } }
                            .buttonStyle(.bordered)
                            .disabled(busy)
                    }
                } else {
                    // The one action is the browser sign-in (DESIGN_RULES §9, 2026-10-29: one primary), and a quiet
                    // "Check status" while the browser finishes. No field is drawn: nothing here takes a secret.
                    let action = ConnectorSetupState.action(status)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        if awaitingAuthorization {
                            TextButton(title: "Check status", flushLeading: true) { Task { await checkStatus() } }
                                .disabled(busy)
                                .accessibilityLabel("Check whether \(status.label) finished connecting")
                        }
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if action != .none {
                            let title = action == .signInAgain ? Copy.SourceLayout.reconnect
                                                               : Copy.Connect.connect(status.label)
                            // No return shortcut: this panel also sits inline on a source's detail, where it is the page's.
                            PrimaryActionButton(title: title) { Task { await authorize() } }
                                .disabled(busy)
                                .accessibilityLabel(title)
                        }
                    }
                }
            } else {
                ProgressView().controlSize(.small)
            }

            if !vendors.isEmpty {
                Divider().background(CicadaTheme.border)
                Text(Copy.connectorExportBackfill)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                WalkthroughPanel(vendors: vendors, vendor: $vendor) {}
            }

            if let message {
                Text(message).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.success)
            }
            if let error {
                Text(error).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
            }
        }
        .task { await load() }
        .onDisappear {
            // H1 discipline: an abandoned poll must not keep running (or
            // write into this view's @State) once the panel is gone.
            pollTask?.cancel()
            pollTask = nil
        }
    }

    private func load() async {
        do {
            let all = try await APIClient.shared.fetchConnectors()
            status = all.first { $0.id == connectorId }
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func authorize() async {
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.authorizeConnector(connectorId)
            if let url = URL(string: result.authorizeUrl) { NSWorkspace.shared.open(url) }
            message = Copy.connectorAuthorizeHint
            error = nil
            // Fix round 1, M1: the panel used to dead-end here — nothing
            // reloaded `status` after the browser round trip. Now it both
            // offers a manual "Check status" button (via
            // `awaitingAuthorization`) and starts a bounded auto-poll.
            awaitingAuthorization = true
            startPolling()
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    /// Manual "Check status" affordance (fix round 1, M1) — re-fetches this
    /// connector's status on demand, for a user who doesn't want to wait out
    /// the automatic poll (or came back after it timed out).
    private func checkStatus() async {
        busy = true
        defer { busy = false }
        await load()
        if status?.connected == true {
            await finishAuthorizing()
        }
    }

    /// Bounded auto-poll kicked off by `authorize()`: every 3s for up to 2
    /// minutes, re-checks whether the browser round trip finished. Cancelled
    /// (and its handle cleared) in `onDisappear`, mirroring
    /// `AddSourceSheet.importTask`'s H1 discipline, so a poll that outlives
    /// the panel can never land on state nobody is looking at anymore.
    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            for _ in 0..<Self.maxPollAttempts {
                try? await Task.sleep(nanoseconds: Self.pollIntervalNanoseconds)
                if Task.isCancelled { return }
                await load()
                if status?.connected == true {
                    await finishAuthorizing()
                    return
                }
            }
            // Timed out after ~2 minutes — leave `awaitingAuthorization`
            // true so "Check status" stays available for a manual retry.
        }
    }

    /// Shared by the poll loop and the manual "Check status" button: stop
    /// polling and pick up the freshly-connected channel state.
    private func finishAuthorizing() async {
        awaitingAuthorization = false
        pollTask?.cancel()
        pollTask = nil
        message = nil
        await store.refresh([.channels])
    }

    private func syncNow() async {
        busy = true
        defer { busy = false }
        do {
            message = ConnectorSetupState.syncSummary(
                try await APIClient.shared.syncConnector(connectorId))
            error = nil
            await load()
            await store.refresh([.channels])
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func disconnect() async {
        busy = true
        defer { busy = false }
        do {
            status = try await APIClient.shared.forgetConnector(connectorId)
            message = "Disconnected."
            error = nil
            awaitingAuthorization = false
            pollTask?.cancel()
            pollTask = nil
            await store.refresh([.channels])
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }
}
