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
            return "\(newPart) · \(result.seen) seen"
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

    @State private var status: ConnectorStatus?
    @State private var drafts: [String: String] = [:]
    @State private var busy = false
    @State private var message: String?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let status {
                Text(ConnectorSetupState.stepLabel(status))
                    .font(.system(size: 12, weight: .semibold))
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
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func syncNow() async {
        busy = true
        defer { busy = false }
        do {
            message = ConnectorSetupState.syncSummary(
                try await APIClient.shared.syncConnector(connectorId))
            error = nil
            await load()
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
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }
}
