import Foundation

/// DR-42 — one answer held for its Undo window (R-DI2). Undo is a SEND DELAY, not a revert:
/// `POST /inbox/{id}/resolve` leaves only when the window closes, when the next answer starts, or
/// before a bank switch, the main window closing or a quit (R-DI3). An undone answer therefore
/// writes no commit, no claim and no G113 `resolution` event — there is nothing to revert. The
/// send itself is the ordinary `InboxResolve` mutation: its optimistic hide, rollback-with-toast
/// and `.inbox` refresh are reused, not re-implemented.
struct ResolveGrace {
    static var window: Duration { .seconds(CicadaTiming.undoWindow) }

    let resolve: InboxResolve
    /// "Answered · sqlite-vec" in the list; the short form beside the Reader (R-DI5).
    let label: String
    let shortLabel: String
    let question: String
    let kind: InboxKind
    /// G129 — a removal's browser channel, so the Sources page shows its own Undo row (R-DI16).
    let channel: String?
    /// Ids repeat across banks (`inbox-001` is in every one): a hold is sent only to its own bank.
    let bank: String
    let token: Int

    var id: String { resolve.id }
}

extension Store {
    /// The held answer, if it belongs to the bank on screen.
    var currentHeld: ResolveGrace? {
        guard let held = heldResolve, held.bank == bank else { return nil }
        return held
    }

    /// What the send delay hides from `visibleInbox`.
    var graceHiddenIds: Set<String> {
        var ids = sendingInboxIds
        if let held = currentHeld { ids.insert(held.id) }
        return ids
    }

    /// Hold an answer for the Undo window. A previous hold is sent NOW, without waiting, so the next
    /// question paints this frame; it moves to `sendingInboxIds` first so it never flashes back.
    func hold(_ resolve: InboxResolve, label: String, shortLabel: String, question: String,
              kind: InboxKind, channel: String?) {
        if let previous = heldResolve {
            heldResolve = nil
            sendingInboxIds.insert(previous.id)
            Task { await self.send(previous) }
        }
        graceToken &+= 1
        let token = graceToken
        heldResolve = ResolveGrace(resolve: resolve, label: label, shortLabel: shortLabel, question: question,
                                   kind: kind, channel: channel, bank: bank, token: token)
        graceTask?.cancel()
        let wait = graceWait
        graceTask = Task { [weak self] in
            await wait(ResolveGrace.window)
            guard !Task.isCancelled else { return }
            await self?.expire(token: token)
        }
    }

    /// Undo inside the window: nothing was sent, so nothing is reverted. Returns the id to reopen.
    @discardableResult
    func undoHeld() -> String? {
        guard let held = heldResolve else { return nil }
        graceTask?.cancel()
        graceTask = nil
        heldResolve = nil
        return held.id
    }

    /// The window closed on its own; a stale token (an Undo, or a newer hold) sends nothing.
    func expire(token: Int) async {
        guard let held = heldResolve, held.token == token else { return }
        await flushHeld()
    }

    /// Send the held answer now: the window's end, a bank switch, the window closing, quit.
    func flushHeld() async {
        guard let held = heldResolve else { return }
        graceTask?.cancel()
        graceTask = nil
        heldResolve = nil
        sendingInboxIds.insert(held.id)
        await send(held)
    }

    private func send(_ held: ResolveGrace) async {
        defer { sendingInboxIds.remove(held.id) }
        guard held.bank == bank else {
            toast = Copy.Inbox.answerNotSaved
            return
        }
        // R-DI3 — answered elsewhere inside the window: a fresh snapshot without the id means the server
        // already closed it, and a POST would 404 into a "reverted" toast. No snapshot at all (a cache
        // miss) is not evidence of that, so it still sends.
        if let items = inbox.value, !items.contains(where: { $0.id == held.id }) { return }
        _ = await perform(held.resolve)
        await onHeldResolveSent?()
    }
}
