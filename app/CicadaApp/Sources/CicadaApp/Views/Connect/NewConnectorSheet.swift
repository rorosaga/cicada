import SwiftUI

/// The New connector sheet (G135, R-R7): pick the app by its mark, name it,
/// choose what it may do in plain verbs, choose when it expires. Then, in the
/// same sheet, the one time the link or token is shown, with that app's own
/// steps (R-R34: the "Other" and header apps get the token; link apps the link).
struct NewConnectorSheet: View {
    var onClose: () -> Void

    @State private var app: RemoteApp = .claude
    @State private var label = ""
    @State private var scopes: Set<RemoteScope> = RemoteScope.defaults
    @State private var expiry: RemoteExpiry = .thirtyDays
    @State private var busy = false
    @State private var problem: String?
    @State private var created: RemoteConnectorCreated?

    var body: some View {
        Group {
            if let created {
                ShownOnceView(created: created, onDone: onClose)
            } else {
                form
            }
        }
        .frame(width: CicadaTheme.scaled(560), height: CicadaTheme.scaled(640))
        .background(CicadaTheme.background)
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    Text("New connector")
                        .font(CicadaTheme.titleFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    section("Which app?") {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(104)), spacing: CicadaTheme.spacingSM)],
                                  spacing: CicadaTheme.spacingSM) {
                            ForEach(RemoteApp.allCases) { candidate in tile(candidate) }
                        }
                        Text(Copy.remoteGeminiApp)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    section("Name") {
                        TextField(app.name, text: $label)
                            .textFieldStyle(.roundedBorder)
                    }
                    section("What it may do") {
                        ForEach(RemoteScope.allCases) { scope in
                            Toggle(isOn: Binding(get: { scopes.contains(scope) },
                                                 set: { on in if on { scopes.insert(scope) } else { scopes.remove(scope) } })) {
                                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                                    Text(scope.title)
                                        .font(CicadaTheme.bodyFont)
                                        .foregroundStyle(CicadaTheme.textPrimary)
                                    Text(scope.detail)
                                        .font(CicadaTheme.captionFont)
                                        .foregroundStyle(CicadaTheme.textTertiary)
                                }
                            }
                            .toggleStyle(.checkbox)
                        }
                        Text(RemoteScope.summary(scopes))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    section("Expires") {
                        Picker("Expires", selection: $expiry) {
                            ForEach(RemoteExpiry.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        if expiry == .never {
                            Text(Copy.remoteNoExpiryWarning)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.warning)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let problem {
                        Text(problem)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.danger)
                    }
                }
                .padding(CicadaTheme.spacingXL)
            }
            Divider()
            HStack {
                Button("Cancel", action: onClose).keyboardShortcut(.cancelAction)
                Spacer()
                Button(busy ? "Creating…" : "Create") { Task { await create() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy || scopes.isEmpty)
            }
            .padding(CicadaTheme.spacingLG)
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(title)
                .font(CicadaTheme.bodyFont.weight(.semibold))
                .foregroundStyle(CicadaTheme.textSecondary)
            content()
        }
    }

    private func tile(_ candidate: RemoteApp) -> some View {
        Button { app = candidate } label: {
            VStack(spacing: CicadaTheme.spacingXS) {
                RemoteAppMark(app: candidate, size: CicadaTheme.scaled(32))
                Text(candidate.name)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(app == candidate ? CicadaTheme.surfaceElevated : CicadaTheme.surface))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(app == candidate ? CicadaTheme.accent : CicadaTheme.border, lineWidth: 1))
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(app == candidate ? .isSelected : [])
    }

    private func create() async {
        busy = true
        problem = nil
        defer { busy = false }
        do {
            created = try await APIClient.shared.createRemoteConnector(
                app: app.rawValue,
                label: label.trimmingCharacters(in: .whitespacesAndNewlines),
                scopes: RemoteScope.allCases.filter(scopes.contains).map(\.rawValue),
                expiresInDays: expiry.days)
        } catch {
            problem = "Couldn't create it: \(error.localizedDescription)"
        }
    }
}

/// The one time a link or token is shown (create or rotate).
struct ShownOnceView: View {
    let created: RemoteConnectorCreated
    var onDone: () -> Void

    private var app: RemoteApp { created.connector.remoteApp }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        RemoteAppMark(app: app, size: CicadaTheme.scaled(40))
                        Text("\(created.connector.label) is ready")
                            .font(CicadaTheme.titleFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                    }
                    if app.usesLink, let link = created.link {
                        Text("Your link")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                        CommandBox(command: link)
                    }
                    if app.usesHeader {
                        Text("Your token")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                        CommandBox(command: created.token)
                    }
                    Label(Copy.remoteShownOnce, systemImage: "eye.slash")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.warning)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                        let steps = app.steps(link: created.link ?? "", mcpURL: created.mcpUrl ?? "", token: created.token)
                        ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                                Text("\(index + 1)")
                                    .font(CicadaTheme.captionFont.weight(.bold))
                                    .foregroundStyle(CicadaTheme.accent)
                                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                                    Text(step.text)
                                        .font(CicadaTheme.bodyFont)
                                        .foregroundStyle(CicadaTheme.textPrimary)
                                        .fixedSize(horizontal: false, vertical: true)
                                    if let snippet = step.snippet { CommandBox(command: snippet) }
                                }
                            }
                        }
                    }
                    if let note = app.note {
                        Text(note)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(CicadaTheme.spacingXL)
            }
            Divider()
            HStack {
                Spacer()
                Button("Done", action: onDone).keyboardShortcut(.defaultAction)
            }
            .padding(CicadaTheme.spacingLG)
        }
    }
}
