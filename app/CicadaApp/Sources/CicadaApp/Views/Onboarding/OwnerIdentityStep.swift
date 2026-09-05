import SwiftUI

/// First-run sheet, step 0 (G117): the one piece of identity the rest of
/// the graph hangs off of. `PUT /settings/owner` is what finally makes
/// `owner_identity.resolve_observer` return something other than the
/// portable `"owner"` keyword — see that module's docstring — so this step
/// runs before the engine/channel/sleep steps rather than after them.
///
/// This step drives its own advance (a "Continue" button, not the sheet's
/// shared Back/Next footer) because moving on requires a network round trip
/// (`updateOwnerSettings`) that can fail — `EngineCard`/`IntegrationsView`,
/// the next two steps, are passive settings panels with nothing to submit,
/// which is why they DO use the shared footer.
struct OwnerIdentityStep: View {
    /// Called once `PUT /settings/owner` succeeds. Owned by `FirstRunSheet`,
    /// which advances `step` in response.
    var onContinue: () -> Void = {}

    @State private var name = ""
    @State private var handle = ""
    @State private var email = ""
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var loadedOnce = false

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                Text("What should Cicada call you?")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Every claim you state yourself gets tagged with this name — never a stand-in.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                field(placeholder: "Your name", text: $name)
                field(placeholder: "Handle (optional)", text: $handle)
                field(placeholder: "Email (optional)", text: $email)

                if let errorMessage {
                    Text(errorMessage)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(.red)
                }

                Button(isSaving ? "Saving…" : "Continue") { Task { await save() } }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
                    .disabled(trimmedName.isEmpty || isSaving)
            }
            .padding(CicadaTheme.spacingXL)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task {
            // Guarded like `EngineCard`'s own `.task` — "Run setup again"
            // reopens this step against an already-onboarded bank, and a
            // re-fetch on every appearance would stomp text the person is
            // mid-typing.
            guard !loadedOnce else { return }
            loadedOnce = true
            if let existing = try? await APIClient.shared.fetchOwnerSettings(), !existing.name.isEmpty {
                name = existing.name
                handle = existing.handle ?? ""
                email = existing.email ?? ""
            }
        }
    }

    private func field(placeholder: String, text: Binding<String>) -> some View {
        TextField(placeholder, text: text)
            .textFieldStyle(.plain)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surfaceHover)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func save() async {
        errorMessage = nil
        isSaving = true
        defer { isSaving = false }
        do {
            _ = try await APIClient.shared.updateOwnerSettings(
                name: trimmedName,
                handle: handle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : handle,
                email: email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : email
            )
            onContinue()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
