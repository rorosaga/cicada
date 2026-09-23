import SwiftUI

/// Settings → You (G139, design §2.2): the owner's name, handle and email over
/// the G117 endpoint onboarding already uses, and a way to the owner's own
/// page. Edits commit on Return or when a field loses focus, and only when
/// something changed (`OwnerDraft`) — each PUT rewrites and commits the owner
/// page under `Cicada-Author: user`, so a focus change with nothing typed must
/// never mint an empty commit. The observer wire id is never shown; the app
/// calls the owner "You" (`CopyConstantsTests.testTheUserObserverIsCalledYou`).
struct YouView: View {
    private enum Field: Hashable { case name, handle, email }

    @Environment(AppRouter.self) private var router
    @State private var saved: OwnerSettings?
    @State private var draft = OwnerDraft()
    @State private var problem: String?
    @FocusState private var focused: Field?

    var body: some View {
        SettingsPage(section: .you) {
            SettingsGroupCard {
                SettingsRow(.ownerName, title: Copy.ownerNameTitle, detail: problem) {
                    field(Copy.ownerNameTitle, text: $draft.name, focus: .name)
                }
                SettingsDivider()
                SettingsRow(.ownerHandle, title: Copy.ownerHandleTitle, detail: Copy.ownerHandleDetail) {
                    field("octocat", text: $draft.handle, focus: .handle)
                }
                SettingsDivider()
                SettingsRow(.ownerEmail, title: Copy.ownerEmailTitle) {
                    field("you@example.com", text: $draft.email, focus: .email).privacySensitive()
                }
            }
            // Only once the owner page exists: a fresh bank has no page to
            // show until the name is first saved (G117 creates it then).
            if let id = saved?.entityId {
                SettingsGroupCard {
                    SettingsRow(.ownerPage, title: Copy.ownerPageTitle, detail: saved?.name) {
                        Button(Copy.showOnGraph) { router.routeToEntity(id) }
                    }
                }
            }
        }
        .task { await load() }
        .onChange(of: focused) { old, _ in if old != nil { commit() } }
    }

    private func field(_ prompt: String, text: Binding<String>, focus: Field) -> some View {
        TextField(prompt, text: text)
            .textFieldStyle(.roundedBorder)
            .frame(width: CicadaTheme.scaled(240))
            .focused($focused, equals: focus)
            .onSubmit(commit)
            // A value is disabled until the saved one has loaded, so a field
            // typed into before the GET lands can't be overwritten by it.
            .disabled(saved == nil)
    }

    private func load() async {
        guard let owner = try? await APIClient.shared.fetchOwnerSettings() else { return }
        saved = owner
        draft = OwnerDraft(owner)
    }

    private func commit() {
        guard saved != nil else { return }
        if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            problem = Copy.ownerNameBlank
            return
        }
        problem = nil
        guard let change = draft.update(from: saved) else { return }
        Task { @MainActor in
            do {
                saved = try await APIClient.shared.updateOwnerSettings(
                    name: change.name, handle: change.handle, email: change.email)
            } catch {
                problem = AddSourceSheet.friendlyError(error)
            }
        }
    }
}
