import SwiftUI

/// G147 — Settings → Memory's "How things fade": what Cicada suggests from your own
/// "Still tracking…?" answers, and the pace you chose per kind of page. Agent proposes, person
/// disposes (UX principle 3): nothing changes how anything fades until Apply. Direction D: one
/// group card of Settings rows (DR-37, DR-33), Apply and Reset neutral and Not now a text button —
/// no primary action on this surface, no accent (DR-40, DR-7, DR-5) — counts through FadeWords'
/// UsageFormat (DR-21), plain sentences with no bare percentages (DR-59), a disabled button that
/// says why (DR-41).
struct FadePaceCard: View {
    @Environment(Store.self) private var store
    @AppStorage(DecayTuningModel.notNowKey) private var notNowRaw = ""
    @State private var response: DecayTuningResponse?
    @State private var note: String?
    @State private var busy = false

    private var rows: [FadeTypeRow] {
        guard let response else { return [] }
        return DecayTuningModel.rows(response, notNow: DecayTuningModel.decodeNotNow(notNowRaw))
    }

    var body: some View {
        SettingsGroupCard(header: Copy.fadeHeader) {
            SettingsRow(.fadePace, title: Copy.fadePaceTitle, detail: note ?? Copy.fadePaceDetail)
            ForEach(rows) { row in
                SettingsDivider()
                typeRow(row)
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func typeRow(_ row: FadeTypeRow) -> some View {
        switch row.kind {
        case .suggestion(let s):
            SettingsRow(.fadeType(row.type), title: FadeWords.suggestionTitle(s),
                        detail: FadeWords.suggestionDetail(s, current: row.current)) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextButton(title: Copy.fadeNotNow) { notNow(s) }
                    NeutralButton(title: Copy.fadeApply, size: .compact, isDisabled: busy,
                                  disabledHelp: Copy.fadeBusyHelp) { write([row.type: s.multiplier]) }
                }
            }
        case .tuned(let value):
            SettingsRow(.fadeType(row.type), title: FadeWords.tunedTitle(type: row.type, multiplier: value),
                        detail: FadeWords.tunedDetail) {
                NeutralButton(title: Copy.fadeReset, size: .compact, isDisabled: busy,
                              disabledHelp: Copy.fadeBusyHelp) { write([row.type: nil]) }
            }
        }
    }

    private func load() async {
        do {
            response = try await APIClient.shared.fetchDecayTuning()
            note = nil
        } catch {
            note = Copy.fadeLoadFailed
        }
    }

    /// R-FD8 — remembered per viewer and per bank with the answer count it was dismissed at.
    private func notNow(_ s: DecaySuggestion) {
        guard let response else { return }
        var map = DecayTuningModel.decodeNotNow(notNowRaw)
        map[DecayTuningModel.notNowID(bank: response.bank, s)] = s.answers
        notNowRaw = DecayTuningModel.encodeNotNow(map)
    }

    private func write(_ changes: [String: Double?]) {
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                response = try await APIClient.shared.setDecayTuning(changes)
                note = nil
                // R-FD9: the card's pace reads the tuning; drop cached bodies so the next open refetches.
                store.invalidateAllEntities()
            } catch APIError.httpError(409, _) {
                note = Copy.sleepIsRunning
            } catch {
                note = Copy.fadeSaveFailed
            }
        }
    }
}
