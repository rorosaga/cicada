import SwiftUI

/// G179 (2026-10-28) — WhatsApp and Telegram on the Sources page → Messaging, drawn exactly as Messages is
/// (`MessagesRow`): the row with its mark, one status line, Refresh and Choose… (DR-40 `NeutralButton`s, DR-38 the head
/// not repeated under a source detail), and a sheet (R-HS16) with the one sentence of what is read, then one row per
/// chat — picture, name, last activity, the tick (`.switch`, mini). Two additions, both existing controls: "Read
/// history" per ticked chat (a `.bordered` small button, as Messages' "Read again"), and for Telegram the sign-in
/// steps in the same sheet with native rounded fields (DR-76: setup sheets keep the native field) and the consent
/// sentence the backend serves, word for word (ruling 47a). No new visual pattern.

// MARK: - WhatsApp

struct WhatsAppSourceRow: View {
    let channel: SourceChannel?
    @Environment(WhatsAppWatcher.self) private var watcher
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var showPanel = false
    @State private var note: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ChatSourceHead(origin: WhatsAppWatcher.channel, title: Copy.Chats.whatsAppTitle, headShown: headShown,
                           line: line, problem: isProblem) {
                if !watcher.tickedIds.isEmpty {
                    NeutralButton(title: Copy.Chats.refresh, size: .compact, isDisabled: watcher.status == .syncing) {
                        Task { note = (try? await watcher.syncNow()) ?? nil }
                    }
                }
                NeutralButton(title: Copy.Chats.choose, size: .compact, help: Copy.Chats.chooseHelp) { showPanel = true }
            }
            .sheet(isPresented: $showPanel) { WhatsAppPanel { showPanel = false } }
            if case .needsAccess(let error) = watcher.status { FullDiskAccessHint(error: error) }
            if channel?.connected == true {
                CapturedItemsList(channel: WhatsAppWatcher.channel)
                    .padding(.leading, headShown ? 0 : CicadaTheme.scaled(28) + CicadaTheme.spacingMD)
            }
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.channel(WhatsAppWatcher.channel))
    }

    private var isProblem: Bool {
        switch watcher.status {
        case .failed, .needsAccess: true
        default: false
        }
    }

    private var line: String {
        switch watcher.status {
        case .failed(let why): return why
        case .needsAccess: return Copy.Chats.whatsAppUnreadable
        case .missing: return Copy.Chats.whatsAppMissing
        default: break
        }
        let base = watcher.tickedIds.isEmpty ? Copy.Chats.rowLineNone : Copy.Chats.rowLine(ticked: watcher.tickedIds.count)
        if let note, watcher.status != .syncing, !watcher.tickedIds.isEmpty { return "\(base) · \(note)" }
        return base
    }
}

struct WhatsAppPanel: View {
    let onDone: () -> Void
    @Environment(WhatsAppWatcher.self) private var watcher
    @State private var error: String?

    var body: some View {
        SettingsSheet(title: Copy.Chats.whatsAppTitle, onClose: onDone) {
            ChatSheetSentence(text: Copy.Chats.whatsAppWhatItReads)
            switch watcher.status {
            case .needsAccess(let fix):
                FullDiskAccessHint(error: fix) { Task { await watcher.loadList() } }
                Button(Copy.Chats.tryAgain) { Task { await watcher.loadList() } }.buttonStyle(.bordered)
            case .missing:
                Text(Copy.Chats.whatsAppMissing).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            default:
                if watcher.listing && watcher.chats.isEmpty {
                    ChatSheetLoading()
                } else if watcher.chats.isEmpty {
                    Text(Copy.Chats.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                } else {
                    ScrollView {
                        VStack(spacing: 2) {
                            ForEach(watcher.chats) { chat in
                                ChatTickRow(name: watcher.name(of: chat), group: chat.group,
                                            last: MessagesRowText.lastActivity(chat.lastActivity),
                                            thumbnail: watcher.cards[chat.id]?.thumbnail,
                                            ticked: watcher.tickedIds.contains(chat.id),
                                            historyRead: watcher.historyIds.contains(chat.id),
                                            onTick: { on in
                                                do { try await watcher.setTicked(chat, on) }
                                                catch { self.error = WhatsAppWatcher.failureMessage(error) }
                                            },
                                            onHistory: {
                                                do { try await watcher.readHistory(chat) }
                                                catch { self.error = WhatsAppWatcher.failureMessage(error) }
                                            })
                            }
                        }
                    }
                    .frame(maxHeight: CicadaTheme.scaled(360))
                }
            }
            ChatSheetFooter(error: error, onDone: onDone)
        }
        .task { await watcher.loadList() }
    }
}

// MARK: - Telegram (ruling 47a)

struct TelegramSourceRow: View {
    let channel: SourceChannel?
    @Environment(TelegramChats.self) private var model
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var showPanel = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ChatSourceHead(origin: TelegramChats.channel, title: Copy.Chats.telegramTitle, headShown: headShown,
                           line: line, problem: model.status.state == "ended") {
                if model.connected {
                    NeutralButton(title: Copy.Chats.choose, size: .compact, help: Copy.Chats.chooseHelp) { showPanel = true }
                } else {
                    NeutralButton(title: Copy.Chats.connect, size: .compact, help: Copy.Chats.connectHelp) { showPanel = true }
                }
            }
            .sheet(isPresented: $showPanel) { TelegramPanel { showPanel = false } }
            if channel?.connected == true {
                CapturedItemsList(channel: TelegramChats.channel)
                    .padding(.leading, headShown ? 0 : CicadaTheme.scaled(28) + CicadaTheme.spacingMD)
            }
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.channel(TelegramChats.channel))
        .task { await model.refresh() }
    }

    private var line: String {
        switch model.status.state {
        case "connected":
            return model.tickedIds.isEmpty ? Copy.Chats.rowLineNone : Copy.Chats.rowLine(ticked: model.tickedIds.count)
        case "ended": return model.status.error ?? Copy.Chats.sessionEnded
        default: return Copy.Chats.notConnected
        }
    }
}

struct TelegramPanel: View {
    let onDone: () -> Void
    @Environment(TelegramChats.self) private var model
    @State private var phone = ""
    @State private var code = ""
    @State private var password = ""
    /// The chat waiting for the person's confirmation that the other person agreed (ruling 47a amendment).
    @State private var asking: TelegramChatRow?

    var body: some View {
        SettingsSheet(title: Copy.Chats.telegramTitle, onClose: onDone) {
            ChatSheetSentence(text: Copy.Chats.telegramWhatItReads)
            if model.connected {
                chatList
                HStack {
                    Spacer()
                    Button(Copy.Chats.disconnect) { Task { await model.disconnect() } }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .help(Copy.Chats.disconnectHelp)
                        .disabled(model.busy)
                }
            } else {
                // The consent sentence is the backend's, word for word (ruling 47a).
                Text(model.status.consent)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                if model.asksPassword {
                    SecureField(Copy.Chats.passwordPrompt, text: $password)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await model.submit(password: password); password = "" } }
                    step(Copy.Chats.signIn, disabled: password.isEmpty) {
                        await model.submit(password: password)
                        password = ""
                    }
                } else if model.asksCode {
                    TextField(Copy.Chats.codePrompt, text: $code)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await model.submit(code: code); code = "" } }
                    step(Copy.Chats.signIn, disabled: code.isEmpty) {
                        await model.submit(code: code)
                        code = ""
                    }
                } else {
                    TextField(Copy.Chats.phonePrompt, text: $phone)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await model.connect(phone: phone) } }
                    step(Copy.Chats.sendCode, disabled: phone.isEmpty) {
                        await model.connect(phone: phone)
                        phone = ""
                    }
                }
            }
            ChatSheetFooter(error: model.error, onDone: onDone)
        }
        .task {
            await model.refresh()
            await model.loadChats()
        }
        .onChange(of: model.connected) { _, now in if now { Task { await model.loadChats() } } }
        // A system alert, the one confirmation pattern macOS has (no new visual pattern): the sentence, then
        // "They agreed" or Cancel. Nothing is ticked or read until the person confirms.
        .alert(Copy.Chats.consentTitle, isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }),
               presenting: asking) { chat in
            Button(Copy.Chats.consentYes) { Task { await model.setTicked(chat, true, consent: true) } }
            Button(Copy.Chats.consentCancel, role: .cancel) {}
        } message: { chat in
            Text(model.consentAsk(for: chat))
        }
    }

    private func step(_ title: String, disabled: Bool, _ action: @escaping () async -> Void) -> some View {
        HStack {
            Spacer()
            Button(title) { Task { await action() } }
                .buttonStyle(.borderedProminent)
                .disabled(disabled || model.busy)
        }
    }

    @ViewBuilder
    private var chatList: some View {
        if model.listing && model.chats.isEmpty {
            ChatSheetLoading()
        } else if model.chats.isEmpty {
            Text(Copy.Chats.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
        } else {
            ScrollView {
                VStack(spacing: 2) {
                    ForEach(model.chats) { chat in
                        ChatTickRow(name: chat.name.isEmpty ? Copy.Chats.unnamed : chat.name, group: false,
                                    last: chat.last.flatMap { ISO8601DateFormatter().date(from: $0) }
                                        .flatMap { MessagesRowText.lastActivity($0) },
                                    thumbnail: nil, ticked: model.tickedIds.contains(chat.id),
                                    historyRead: model.historyIds.contains(chat.id),
                                    onTick: { on in
                                        if on { asking = chat } else { await model.setTicked(chat, false, consent: false) }
                                    },
                                    onHistory: { await model.readHistory(chat) })
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(360))
        }
    }
}

// MARK: - The shared pieces (the Messages row's, unchanged)

/// The row's head: the source's mark and name (hidden under a source detail's own head, DR-38), the status line,
/// then the trailing buttons.
struct ChatSourceHead<Trailing: View>: View {
    let origin: String
    let title: String
    let headShown: Bool
    let line: String
    let problem: Bool
    @ViewBuilder let trailing: Trailing

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if !headShown {
                LogoImage.platformTile(name: OriginIconography.logoName(for: origin) ?? "",
                                       bundleId: OriginIconography.appBundleId(for: origin),
                                       size: CicadaTheme.scaled(28),
                                       systemFallback: OriginIconography.symbol(for: origin))
            }
            VStack(alignment: .leading, spacing: 2) {
                if !headShown {
                    Text(title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                Text(line)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(problem ? CicadaTheme.danger : CicadaTheme.textSecondary)
            }
            Spacer()
            trailing
        }
    }
}

struct ChatSheetSentence: View {
    let text: String
    var body: some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

struct ChatSheetLoading: View {
    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ProgressView().controlSize(.small)
            Text(Copy.Chats.loading).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

struct ChatSheetFooter: View {
    let error: String?
    let onDone: () -> Void
    var body: some View {
        if let error {
            Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
        }
        HStack {
            Spacer()
            Button(Copy.Chats.done, action: onDone)
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
        }
    }
}

/// One chat: its picture, name, a group tag (DR-44's one pill), last activity, "Read history" once ticked, the tick.
struct ChatTickRow: View {
    let name: String
    let group: Bool
    let last: String?
    let thumbnail: Data?
    let ticked: Bool
    let historyRead: Bool
    let onTick: (Bool) async -> Void
    let onHistory: () async -> Void
    @State private var busy = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            avatar
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if group { Tag(text: Copy.Chats.group) }
                }
                if let last {
                    Text(last).font(CicadaTheme.captionFont).monospacedDigit().foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if ticked {
                if historyRead {
                    Text(Copy.Chats.historyAsked).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                } else {
                    Button(Copy.Chats.readHistory) { run { await onHistory() } }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .help(Copy.Chats.readHistoryHelp)
                        .disabled(busy)
                }
            }
            Toggle(Copy.Chats.tickHelp, isOn: Binding(get: { ticked }, set: { on in run { await onTick(on) } }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .disabled(busy)
                .help(Copy.Chats.tickHelp)
        }
        .padding(.vertical, CicadaTheme.scaled(4))
    }

    private func run(_ body: @escaping () async -> Void) {
        busy = true
        Task {
            await body()
            busy = false
        }
    }

    @ViewBuilder
    private var avatar: some View {
        let side = CicadaTheme.scaled(28)
        Group {
            if let thumbnail, let image = NSImage(data: thumbnail) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                EntityPictureFallback(type: .person, name: name, units: 28, frame: CGSize(width: side, height: side))
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
    }
}
