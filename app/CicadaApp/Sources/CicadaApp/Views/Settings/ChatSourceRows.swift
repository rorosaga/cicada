import CoreImage
import SwiftUI

/// G179 (2026-10-28) — WhatsApp and Telegram on the Sources page → Messaging, drawn exactly as Messages is
/// (`MessagesRow`): the row with its mark, one status line, Refresh and Choose… (DR-40 `NeutralButton`s, DR-38 the head
/// not repeated under a source detail), and a sheet (R-HS16) with the one sentence of what is read, then one row per
/// chat — picture, name, last activity, the tick (`.switch`, mini). Two additions, both existing controls: "Read
/// history" per ticked chat (a `.bordered` small button, as Messages' "Read again"), and for Telegram the sign-in
/// steps in the same sheet with native rounded fields (DR-76: setup sheets keep the native field) and the consent
/// sentence the backend serves, word for word (ruling 47a). No new visual pattern.
///
/// Owner 2026-10-29 — Telegram connects like linking a desktop: the sheet opens on a sign-in QR the person scans in
/// Telegram on their phone (Settings → Devices → Link Desktop Device), nothing typed but a two-step password; "Use a
/// phone number instead" (a `TextButton`, DR-40) keeps number → code. The QR is a picture inside the same sheet, drawn
/// dark on light whatever the appearance (a scanner needs it), on a `cornerRadiusSmall` tile with the resting ring
/// (DR-9: depth is a ring, never a shadow); its words sit under it, never on it (DR-13).
///
/// Owner 2026-10-29 — "more modern and minimal, with the country codes": the sheet follows the connect sheets' one
/// shape (`ConnectSheet.swift`, DESIGN_RULES §9 2026-10-29) — one step and one primary at a time, no Done until
/// connected, the facts in one line plus "What Cicada reads", a country picker and a five-cell code.

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
    @State private var query = ""

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
                    ChatSearchField(prompt: Copy.Chats.searchPromptNumber, query: $query)
                    let shown = watcher.filtered(query)
                    if shown.isEmpty { ChatNoMatches(query: query) }
                    ScrollView {
                        LazyVStack(spacing: 2) {
                            ForEach(shown) { chat in
                                ChatTickRow(name: watcher.name(of: chat), group: chat.group,
                                            last: MessagesRowText.lastActivity(chat.lastActivity),
                                            thumbnail: watcher.thumbnail(of: chat),
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
    @State private var country = PhoneCountry.default()
    @State private var national = ""
    @State private var code = ""
    @State private var password = ""
    /// The fallback: the person chose to type their number (the QR is the default).
    @State private var usePhone = false
    /// A page of the sheet shown instead of the step: the full words, or the country list (never a fold or popover).
    @State private var page: Page?
    /// The chat waiting for the person's confirmation that the other person agreed (ruling 47a amendment).
    @State private var asking: TelegramChatRow?
    @State private var query = ""

    enum Page { case facts, countries }

    var body: some View {
        SettingsSheet(title: Copy.Chats.telegramTitle, onClose: onDone) {
            switch page {
            case .facts:
                ConnectFactsPage(paragraphs: [Copy.Chats.telegramWhatItReads, model.status.consent]) { page = nil }
            case .countries:
                CountryList(selected: country, onPick: { country = $0; page = nil }, onBack: { page = nil })
            case nil:
                if model.connected { connectedStep } else { signInStep }
            }
        }
        .task {
            await model.refresh()
            if model.connected {
                await model.loadChats()
            } else if !model.asksCode && !model.asksPassword && !model.showsQR {
                await model.startQR()     // Connect… was the person's act: the sheet opens on the code to scan
            }
        }
        // One status read a second while a QR is on screen; it stops the moment the state moves on.
        .task(id: model.status.state) { if model.status.state == "qr" { await model.followQR() } }
        // Closing the sheet mid sign-in (a QR up or still being asked for, a code or password waiting) stops it at the
        // backend: no unsigned client outlives the sheet that asked.
        .onDisappear { Task { await model.abandonSignIn() } }
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

    // MARK: Steps

    /// Signed in: what's next in one line, the chats, then Disconnect and the sheet's only "Done".
    @ViewBuilder
    private var connectedStep: some View {
        Text(Copy.Chats.connectedLine)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
        chatList
        errorLine
        HStack(spacing: CicadaTheme.spacingSM) {
            TextButton(title: Copy.Chats.disconnect, help: Copy.Chats.disconnectHelp, flushLeading: true) {
                Task { await model.disconnect() }
            }
            .disabled(model.busy)
            Spacer()
            PrimaryActionButton(title: Copy.Connect.done, action: onDone).keyboardShortcut(.defaultAction)
        }
    }

    /// One step at a time: the QR by default; number → code; a two-step password either way.
    @ViewBuilder
    private var signInStep: some View {
        if model.asksPassword {
            stepLine(Copy.Chats.passwordHow)
            SecureField(Copy.Chats.passwordPrompt, text: $password)
                .textFieldStyle(.roundedBorder)
                .controlSize(.large)
            footer
            ConnectSheetActions(primary: Copy.Connect.continueStep, primaryDisabled: password.isEmpty || model.busy,
                                onPrimary: sendPassword, onCancel: onDone)
        } else if model.asksCode {
            stepLine(Copy.Chats.codeHow)
            OneTimeCodeField(code: $code, length: model.codeLength) { _ in sendCode() }
                .frame(maxWidth: .infinity)
                .padding(.vertical, CicadaTheme.spacingSM)
            footer
            ConnectSheetActions(primary: Copy.Connect.continueStep,
                                primaryDisabled: code.count < model.codeLength || model.busy,
                                onPrimary: sendCode, onCancel: onDone)
        } else if usePhone {
            stepLine(Copy.Chats.phoneHow)
            PhoneNumberEntry(country: $country, national: $national, onPickCountry: { page = .countries })
            footer
            ConnectSheetActions(leading: AnyView(TextButton(title: Copy.Chats.useQR, flushLeading: true) {
                                    usePhone = false
                                    model.clearError()
                                    Task { await model.startQR() }
                                }),
                                primary: Copy.Connect.continueStep,
                                primaryDisabled: !PhoneCountry.plausible(national) || model.busy,
                                onPrimary: sendPhone, onCancel: onDone)
        } else {
            qrStep
            footer
            ConnectSheetActions(primary: nil, onCancel: onDone)
        }
    }

    /// The default connect: the code large and centred, one line of how, the fallback beneath it.
    @ViewBuilder
    private var qrStep: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            let side = CicadaTheme.scaled(200)
            Group {
                if model.showsQR, let url = model.status.qrUrl, let image = TelegramQRCode.image(for: url) {
                    Image(nsImage: image)
                        .interpolation(.none)
                        .resizable()
                        .accessibilityLabel(Copy.Chats.qrAccessibility)
                        .help(Copy.Chats.qrRefreshes)
                } else if model.busy {
                    ProgressView().controlSize(.small)
                } else {
                    NeutralButton(title: Copy.Chats.qrAgain, size: .compact, help: Copy.Chats.connectHelp) {
                        Task { await model.startQR() }
                    }
                }
            }
            .frame(width: side, height: side)
            .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
            .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            if model.showsQR || model.busy {
                Text(model.showsQR ? Copy.Chats.qrHow : Copy.Chats.qrStarting)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TextButton(title: Copy.Chats.usePhone) {
                usePhone = true
                model.clearError()
                if model.showsQR { Task { await model.disconnect() } }   // stops the QR; nothing was signed in
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    /// Under every sign-in step: a refusal in the backend's words, then the one line of what is read and the
    /// backend's session sentence, word for word (ruling 47a), with the full words one click away.
    @ViewBuilder
    private var footer: some View {
        errorLine
        ConnectFactsLine(text: "\(Copy.Chats.telegramFacts) \(model.status.consent)") { page = .facts }
    }

    @ViewBuilder
    private var errorLine: some View {
        if let error = model.error {
            Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func stepLine(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func sendPhone() {
        guard PhoneCountry.plausible(national), !model.busy else { return }
        let number = country.international(national)
        Task { await model.connect(phone: number) }
    }

    private func sendCode() {
        guard code.count >= model.codeLength, !model.busy else { return }
        let typed = code
        code = ""
        Task { await model.submit(code: typed) }
    }

    private func sendPassword() {
        guard !password.isEmpty, !model.busy else { return }
        let typed = password
        password = ""
        Task { await model.submit(password: typed) }
    }

    @ViewBuilder
    private var chatList: some View {
        if model.listing && model.chats.isEmpty {
            ChatSheetLoading()
        } else if model.chats.isEmpty {
            Text(Copy.Chats.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
        } else {
            ChatSearchField(prompt: Copy.Chats.searchPrompt, query: $query)
            let shown = ChatSearch.filter(model.chats, query: query, name: \.shownName)
            if shown.isEmpty { ChatNoMatches(query: query) }
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(shown) { chat in
                        ChatTickRow(name: chat.shownName, group: false,
                                    last: chat.last.flatMap { ISO8601DateFormatter().date(from: $0) }
                                        .flatMap { MessagesRowText.lastActivity($0) },
                                    thumbnail: model.photos[chat.id], ticked: model.tickedIds.contains(chat.id),
                                    historyRead: model.historyIds.contains(chat.id),
                                    onTick: { on in
                                        // Saved Messages has no other person to ask about (47a amendment 2026-10-29).
                                        if on && !chat.own { asking = chat }
                                        else { await model.setTicked(chat, on, consent: false) }
                                    },
                                    onHistory: { await model.readHistory(chat) })
                            // chats-ux-v2 — the row's picture is asked when the row shows (a lazy list: never all 200).
                            .task(id: chat.id) { await model.loadPhoto(chat) }
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(360))
        }
    }
}

/// A `tg://login` link drawn as a QR with Core Image — on this Mac, no service asked. Dark modules on a light ground
/// in both appearances: a phone's scanner reads that, and the generator's own colours are kept rather than tinted.
enum TelegramQRCode {
    static func image(for text: String, scale: CGFloat = 8) -> NSImage? {
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        filter.setValue(Data(text.utf8), forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let code = filter.outputImage else { return nil }
        // The four-module quiet zone the QR spec asks for, in the code's own light ground — so the sheet's dark
        // ground never touches the modules and a scanner finds the edge in either appearance.
        let ground = CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: code.extent.insetBy(dx: -4, dy: -4))
        let scaled = code.composited(over: ground).transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let output = scaled.transformed(by: CGAffineTransform(translationX: -scaled.extent.minX, y: -scaled.extent.minY))
        let rep = NSCIImageRep(ciImage: output)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
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

/// chats-ux-v2 (owner 2026-10-29: "why I can't search my chats like I can inside WhatsApp and Telegram") — the chat
/// picker's search, at the top of the list as the apps put it. A setup sheet keeps the native rounded field (DR-76);
/// the list under it keeps its order, most recent first.
struct ChatSearchField: View {
    let prompt: String
    @Binding var query: String

    var body: some View {
        TextField(prompt, text: $query)
            .textFieldStyle(.roundedBorder)
            .accessibilityLabel(prompt)
    }
}

struct ChatNoMatches: View {
    let query: String
    var body: some View {
        Text(Copy.Chats.noMatches(query)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
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
