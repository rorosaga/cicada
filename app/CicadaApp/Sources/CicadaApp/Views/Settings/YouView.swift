import SwiftUI

/// Settings → You (G139, G117; ruling 36 D6): the owner's name and photo, the email the photo ladder hashes, and
/// *Your profiles* — any profile link pasted as-is. The profiles are the owner page's *Where to check* links
/// (`/entities/{owner}/sources`, G61), so an agent reads them as the places to look for news about the person; a
/// GitHub handle saved before D6 shows here as its profile link and keeps feeding the photo. Edits to the name and the
/// email commit on Return or when a field loses focus, and only when something changed (`OwnerDraft`) — each PUT
/// rewrites and commits the owner page under `Cicada-Author: user`. The observer wire id is never shown.
struct YouView: View {
    private enum Field: Hashable { case name, email, link }

    @Environment(AppRouter.self) private var router
    @Environment(Store.self) private var store
    @State private var saved: OwnerSettings?
    @State private var draft = OwnerDraft()
    @State private var problem: String?
    @State private var profiles: [EntitySource] = []
    @State private var link = ""
    @FocusState private var focused: Field?

    var body: some View {
        SettingsPage(section: .you) {
            SettingsGroupCard {
                HStack(spacing: CicadaTheme.spacingMD) {
                    if let id = saved?.entityId {
                        EntityPicture(id: id, name: saved?.name ?? "", type: .person, size: 44, editing: .tile)
                            .settingsRow(.ownerPhoto)
                    }
                    SettingsRow(.ownerName, title: Copy.ownerNameTitle, detail: problem) {
                        field(Copy.ownerNameTitle, text: $draft.name, focus: .name)
                    }
                }
                .padding(.leading, saved?.entityId == nil ? 0 : CicadaTheme.spacingMD)
                SettingsDivider()
                SettingsRow(.ownerEmail, title: Copy.ownerEmailTitle) {
                    field("you@example.com", text: $draft.email, focus: .email).privacySensitive()
                }
            }
            if saved?.entityId != nil {
                SettingsGroupCard(header: Copy.Profiles.title) {
                    ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                        if index > 0 { SettingsDivider() }
                        ConnectionLine(logo: ProfileLink.mark(row.url), name: ProfileLink.label(row.url),
                                       systemFallback: "link") {
                            if ProfileLink.needsConnecting(row.url) {
                                TextButton(title: Copy.Profiles.connect, inline: true) { router.routeToPage(.sources) }
                            }
                            TextButton(title: Copy.Profiles.remove, inline: true) { remove(row) }
                        }
                    }
                    if !rows.isEmpty { SettingsDivider() }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        TextField(Copy.Profiles.paste, text: $link)
                            .textFieldStyle(.roundedBorder)
                            .focused($focused, equals: .link)
                            .onSubmit(addLink)
                        NeutralButton(title: Copy.Profiles.add, size: .compact,
                                      isDisabled: ProfileLink.normalized(link) == nil) { addLink() }
                    }
                    .padding(CicadaTheme.spacingMD)
                }
                .settingsRow(.ownerProfiles)
            }
        }
        .task { await load() }
        .onChange(of: focused) { old, _ in if old == .name || old == .email { commit() } }
    }

    /// The owner page's url sources, plus the saved GitHub handle as its profile link when no source names it.
    private var rows: [ProfileRow] {
        var out = profiles.enumerated().filter { $0.element.kind == "url" }
            .map { ProfileRow(url: $0.element.ref, index: $0.offset) }
        if let handle = saved?.handle, !handle.isEmpty {
            let url = "https://github.com/\(handle)"
            if !out.contains(where: { $0.url.lowercased().contains("github.com/\(handle.lowercased())") }) {
                out.insert(ProfileRow(url: url, index: nil), at: 0)
            }
        }
        return out
    }

    private func field(_ prompt: String, text: Binding<String>, focus: Field) -> some View {
        TextField(prompt, text: text)
            .textFieldStyle(.roundedBorder)
            .frame(width: CicadaTheme.scaled(240))
            .focused($focused, equals: focus)
            .onSubmit(commit)
            // A value is disabled until the saved one has loaded, so a field typed into before the GET lands can't
            // be overwritten by it.
            .disabled(saved == nil)
    }

    private func load() async {
        guard let owner = try? await APIClient.shared.fetchOwnerSettings() else { return }
        saved = owner
        draft = OwnerDraft(owner)
        if let id = owner.entityId { profiles = (try? await APIClient.shared.fetchEntitySources(entityId: id)) ?? [] }
    }

    private func commit() {
        guard saved != nil else { return }
        if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            problem = Copy.ownerNameBlank
            return
        }
        problem = nil
        guard let change = draft.update(from: saved) else { return }
        let origin = BankScope.onScreen   // G183(d): the owner page lives in this bank
        Task { @MainActor in
            do {
                saved = try await BankScope.bound(to: origin) {
                    try await APIClient.shared.updateOwnerSettings(name: change.name, handle: change.handle,
                                                                   email: change.email)
                }
            } catch {
                problem = AddSourceSheet.friendlyError(error)
            }
        }
    }

    private func addLink() {
        guard let url = ProfileLink.normalized(link), let id = saved?.entityId else { return }
        let origin = BankScope.onScreen
        Task { @MainActor in
            do {
                profiles = try await BankScope.bound(to: origin) {
                    try await APIClient.shared.addEntitySource(entityId: id, ref: url)
                }
                link = ""
            } catch {
                problem = AddSourceSheet.friendlyError(error)
            }
        }
    }

    private func remove(_ row: ProfileRow) {
        guard let saved, let id = saved.entityId else { return }
        let origin = BankScope.onScreen
        Task { @MainActor in
            do {
                if let index = row.index {
                    profiles = try await BankScope.bound(to: origin) {
                        try await APIClient.shared.deleteEntitySource(entityId: id, index: index)
                    }
                } else {
                    // The pre-D6 GitHub handle: clearing it is the person's remove.
                    self.saved = try await BankScope.bound(to: origin) {
                        try await APIClient.shared.updateOwnerSettings(name: saved.name, handle: "", email: saved.email)
                    }
                    draft = OwnerDraft(self.saved ?? saved)
                }
            } catch {
                problem = AddSourceSheet.friendlyError(error)
            }
        }
    }
}

private struct ProfileRow: Identifiable {
    let url: String
    /// The source's index on the owner page; nil for the GitHub handle shown as a link.
    let index: Int?
    var id: String { "\(index.map(String.init) ?? "handle"):\(url)" }
}

/// A pasted profile link, as-is: any site (owner, 2026-10-22: "it might as well be a personal website, a google
/// scholar account or anything"). The mark is the service's own bundled one when the set has it (no fetch, DR-52),
/// the link glyph otherwise.
enum ProfileLink {
    static func normalized(_ raw: String) -> String? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(" ") else { return nil }
        let withScheme = text.contains("://") ? text : "https://\(text)"
        guard let url = URL(string: withScheme), let host = url.host, host.contains("."),
              ["http", "https"].contains(url.scheme ?? "") else { return nil }
        return withScheme
    }

    static func host(_ url: String) -> String {
        let host = URL(string: url)?.host?.lowercased() ?? url
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    /// The link without its scheme — what the person pasted, readable.
    static func label(_ url: String) -> String {
        var text = url
        for prefix in ["https://", "http://"] where text.hasPrefix(prefix) { text = String(text.dropFirst(prefix.count)) }
        if text.hasPrefix("www.") { text = String(text.dropFirst(4)) }
        return text.hasSuffix("/") ? String(text.dropLast()) : text
    }

    static func mark(_ url: String) -> String? {
        let host = host(url)
        let table: [(String, String)] = [
            ("x.com", "x"), ("twitter.com", "x"), ("linkedin.com", "linkedin"), ("github.com", "github"),
            ("instagram.com", "instagram"), ("youtube.com", "youtube"), ("scholar.google.", "scholar"),
            ("reddit.com", "reddit"), ("tiktok.com", "tiktok"), ("pinterest.", "pinterest"), ("spotify.com", "spotify"),
            ("t.me", "telegram"), ("telegram.", "telegram"), ("wa.me", "whatsapp"), ("notion.", "notion"),
        ]
        return table.first { host == $0.0 || host.hasSuffix("." + $0.0) || ($0.0.hasSuffix(".") && host.contains($0.0)) }?.1
    }

    /// Only a service Cicada reads through a connection the person makes (its saved list) offers *Connect*; the
    /// connection itself lives on the Sources page.
    static func needsConnecting(_ url: String) -> Bool {
        ["x", "reddit", "pinterest"].contains(mark(url) ?? "")
    }
}
