import Foundation
import Observation

/// Ruling 47a, G179 (2026-10-28) — Telegram's row: the person connects their own account — by default a QR they scan
/// in Telegram on their phone, like linking a desktop (owner 2026-10-29); number → code as the fallback; a two-step
/// password either way — ticks one-to-one chats — each only after confirming the other person agreed (the 47a amendment, owner
/// 2026-10-28) — and can end the session with one click. The BACKEND holds the client and the session
/// (`api/services/telegram_account.py`); the app only shows the steps and the tick list, so nothing here reads a file
/// or opens a socket to Telegram. The connect step shows the backend's consent sentence word for word.
@MainActor
@Observable
final class TelegramChats {
    nonisolated static let channel = "telegram-chats"
    nonisolated static let source = "telegram"

    private(set) var status = TelegramStatusAnswer()
    private(set) var chats: [TelegramChatRow] = []
    private(set) var tickedIds: Set<String> = []
    private(set) var historyIds: Set<String> = []
    private(set) var listing = false
    private(set) var busy = false
    private(set) var error: String?

    @ObservationIgnored private let api: any ChatSourcesAPI

    init(api: any ChatSourcesAPI = APIClient.shared) { self.api = api }

    var connected: Bool { status.state == "connected" }
    var showsQR: Bool { status.state == "qr" && status.qrUrl != nil }
    var asksCode: Bool { status.state == "code_sent" }
    var asksPassword: Bool { status.state == "password" }

    func refresh() async {
        if let answer = try? await api.telegramStatus() { status = answer }
        if let ticks = try? await api.fetchChatTicks(source: Self.source) {
            tickedIds = ticks.tickedIds
            historyIds = Set(ticks.conversations.filter(\.history).map(\.id))
        }
    }

    func bankChanged() async { await refresh() }

    /// The person moved to another way in (QR or phone): the last way's refusal no longer applies.
    func clearError() { error = nil }

    private func step(_ body: () async throws -> TelegramStatusAnswer) async {
        busy = true
        defer { busy = false }
        do {
            status = try await body()
            error = status.error
        } catch {
            self.error = Self.message(error)
        }
    }

    /// Whether the sheet that asked for a sign-in is still open: a QR answered after it closed is stopped at once.
    @ObservationIgnored private var signInWanted = false

    /// The default connect: the backend asks Telegram for a sign-in QR and answers with the link to draw.
    func startQR() async {
        signInWanted = true
        await step { try await api.telegramQR() }
        if !signInWanted { await abandonSignIn() }
    }

    /// The sheet closed: a sign-in half done — a QR on screen, one still being asked for, a code or a two-step
    /// password waiting — is stopped at the backend, which closes its unsigned client (no log-out: nothing was signed
    /// in). A connected session is never touched.
    func abandonSignIn() async {
        signInWanted = false
        guard ["qr", "code_sent", "password"].contains(status.state) else { return }
        await step { try await api.telegramDisconnect() }
    }

    /// While a QR is on screen: the backend swaps in a fresh one as Telegram expires it, and moves to `connected`
    /// (or `password`) the moment the phone accepts it. One status read a second, only while the sheet shows a QR.
    func followQR(every interval: Duration = .seconds(1)) async {
        while status.state == "qr", !Task.isCancelled {
            try? await Task.sleep(for: interval)
            guard !Task.isCancelled, let answer = try? await api.telegramStatus() else { continue }
            status = answer
            error = answer.error
        }
    }

    func connect(phone: String) async {
        signInWanted = true
        await step { try await api.telegramConnect(phone: phone) }
        if !signInWanted { await abandonSignIn() }
    }
    func submit(code: String) async { await step { try await api.telegramCode(code) } }
    func submit(password: String) async { await step { try await api.telegramPassword(password) } }

    func disconnect() async {
        await step { try await api.telegramDisconnect() }
        chats = []
    }

    func loadChats() async {
        guard connected else { return }
        listing = true
        defer { listing = false }
        do {
            chats = try await api.telegramChats().chats
            tickedIds = Set(chats.filter(\.ticked).map(\.id)).union(tickedIds.subtracting(chats.map(\.id)))
            historyIds = Set(chats.filter(\.history).map(\.id))
        } catch {
            self.error = Self.message(error)
        }
    }

    /// A tick is live from now and carries the person's confirmation that the other person agreed (ruling 47a
    /// amendment: the panel asks first); unticking withdraws it. The backend reads it from its own Telegram client.
    func setTicked(_ chat: TelegramChatRow, _ on: Bool, consent: Bool) async {
        do {
            let answer = try await api.telegramTick(id: chat.id, name: chat.name, ticked: on, consent: on && consent)
            tickedIds = answer.tickedIds
        } catch {
            self.error = Self.message(error)
        }
    }

    /// The per-chat confirmation, in plain words, with the chat's name in it.
    func consentAsk(for chat: TelegramChatRow) -> String {
        status.consentAsk.replacingOccurrences(of: "{name}", with: chat.name.isEmpty ? Copy.Chats.theOtherPerson : chat.name)
    }

    /// The person's ask: the chat's history, read by the backend in the background back to its first message.
    func readHistory(_ chat: TelegramChatRow) async {
        do {
            let answer = try await api.updateChat(source: Self.source, id: chat.id, name: chat.name, group: chat.group,
                                                  ticked: nil, history: true)
            historyIds = Set(answer.conversations.filter(\.history).map(\.id))
        } catch {
            self.error = Self.message(error)
        }
    }

    /// A refusal's sentence is the backend's own (`detail`), else a plain line.
    static func message(_ error: Error) -> String {
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.Chats.syncFailed }
        switch api {
        case .httpError(409, let body), .httpError(422, let body): return ProjectWriteFailure.detail(body) ?? Copy.Chats.syncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.Chats.syncFailed
        }
    }
}
