import AppKit
import SwiftUI

/// The pure copy decisions, hoisted so they are testable without SwiftUI.
enum ConnectorSetupState {

    /// Where the user is in a two-step OAuth setup, or "Connected".
    static func stepLabel(_ status: ConnectorStatus) -> String {
        if status.connected { return "Connected" }
        guard status.isOAuth else { return "Enter your app credentials" }
        let allPresent = !status.fields.isEmpty && status.fields.allSatisfy(\.present)
        return allPresent
            ? "Step 2 of 2 — authorize in your browser"
            : "Step 1 of 2 — save your app keys"
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
    @State private var drafts: [String: String] = [:]
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
                Text(ConnectorSetupState.stepLabel(status))
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)

                if let detail = status.detail ?? status.lastError {
                    Text(detail)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(status.lastError == nil
                                         ? CicadaTheme.textSecondary : CicadaTheme.danger)
                }

                if status.connected {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button("Sync now") { Task { await syncNow() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy)
                        Button("Disconnect", role: .destructive) { Task { await disconnect() } }
                            .buttonStyle(.bordered)
                            .disabled(busy)
                    }
                } else {
                    ForEach(status.fields) { field in
                        credentialRow(field)
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button("Save") { Task { await save() } }
                            .buttonStyle(.bordered)
                            .disabled(busy || drafts.values.allSatisfy { $0.isEmpty })
                        if status.needsAuthorization {
                            Button("Authorize in your browser") { Task { await authorize() } }
                                .buttonStyle(.borderedProminent)
                                .disabled(busy)
                                .accessibilityLabel("Authorize Cicada with \(status.label)")
                        }
                        if awaitingAuthorization {
                            Button("Check status") { Task { await checkStatus() } }
                                .buttonStyle(.bordered)
                                .disabled(busy)
                                .accessibilityLabel("Check whether \(status.label) finished connecting")
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

    @ViewBuilder
    private func credentialRow(_ field: ConnectorField) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(field.label)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: 120, alignment: .leading)
            if field.secret {
                SecureField(field.present ? "Saved — paste to replace" : "Paste value",
                            text: binding(for: field))
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField(field.present ? "Saved — type to replace" : "Paste value",
                          text: binding(for: field))
                    .textFieldStyle(.roundedBorder)
            }
        }
        .accessibilityLabel("\(field.label), \(field.present ? "saved" : "not saved")")
    }

    private func binding(for field: ConnectorField) -> Binding<String> {
        Binding(get: { drafts[field.name] ?? "" },
                set: { drafts[field.name] = $0 })
    }

    private func load() async {
        do {
            let all = try await APIClient.shared.fetchConnectors()
            status = all.first { $0.id == connectorId }
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func save() async {
        busy = true
        defer { busy = false }
        let filled = drafts.filter { !$0.value.trimmingCharacters(in: .whitespaces).isEmpty }
        guard !filled.isEmpty else { return }
        do {
            status = try await APIClient.shared.saveConnectorCredentials(connectorId, fields: filled)
            drafts = [:]
            message = "Saved."
            error = nil
            // Fix round 1, M2 (app side): the backend now bumps
            // sync_state.json on a credential save, so the SSE version
            // vector will eventually catch up — this makes the Feed page's
            // channel badge reflect it immediately instead of waiting on
            // the next poll tick.
            await store.refresh([.channels])
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
