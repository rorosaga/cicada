import SwiftUI

/// R-PP21 — Log progress: one line above the story (the mock). ⏎ saves it as done, ⌘⏎ as still going. The day comes
/// from the words, decided by the server (`when.py`, the one date grammar); the date chip picks it when the words don't
/// say it (the server's own 422 sentence points at the chip); else today. Nothing relative is sent as a value (R-PJ6):
/// the words go as the person wrote them, the chip as `YYYY-MM-DD`. After saving, the day the server chose and how, with
/// Undo for `CicadaTiming.undoWindow` — Undo withdraws the claim the server wrote; the note keeps the person's words.
struct ProjectLogField: View {
    let projectName: String
    let today: ISODay
    let blocked: Bool
    let focus: FocusState<Bool>.Binding
    let save: (_ text: String, _ status: String, _ when: String?) async -> ProjectWriteResponse?
    let undo: (_ claimId: String) async -> Void

    @State private var text = ""
    @State private var day: ISODay?
    @State private var pickerOpen = false
    @State private var saving = false
    @State private var logged: (words: String, claimId: String)?

    private var isEmpty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: "plus.bubble")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                TextField(Copy.Projects.logPlaceholder, text: $text)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.detailBodyFont)
                    .focused(focus)
                    .disabled(blocked)
                    .accessibilityLabel(Copy.Projects.logLabel(projectName))
                    // The palette's split (`FindPanelBody`, `FindKeymap`): plain ⏎ stays on the field's own
                    // `onSubmit`; ⌘⏎ is read here, on the field, and handled so `onSubmit` never also fires.
                    .onSubmit { submit("done") }
                    .onKeyPress(keys: [.return]) { press in
                        guard press.modifiers.contains(.command) else { return .ignored }
                        submit("ongoing")
                        return .handled
                    }
                dateChip
                if isEmpty {
                    KeyHint("L")
                } else {
                    NeutralButton(title: Copy.Projects.logButton, size: .compact, keyHint: "⏎",
                                  isDisabled: blocked || saving, help: Copy.Projects.logHint,
                                  disabledHelp: Copy.Projects.sleepRunningHelp) { submit("done") }
                }
            }
            .padding(.leading, CicadaTheme.spacingMD)
            .padding(.trailing, CicadaTheme.scaled(5))
            .frame(height: CicadaTheme.scaled(38))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
            .ringed(.input, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .help(blocked ? Copy.Projects.sleepRunningHelp : "")
            status.padding(.leading, CicadaTheme.spacingMD)
        }
    }

    @ViewBuilder
    private var status: some View {
        if saving {
            Text(Copy.Projects.saving).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        } else if let logged {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "checkmark").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                Text(logged.words)
                TextButton(title: Copy.Projects.undo, help: Copy.Projects.undoHelp) {
                    let claimId = logged.claimId
                    self.logged = nil
                    Task { await undo(claimId) }
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
        } else if !isEmpty {
            Text(Copy.Projects.logHint).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// The date chip: today's word until one is picked; a native graphical picker, capped at today (a happening is
    /// never in the future).
    private var dateChip: some View {
        TextButton(title: RelativeDay.phrase(day ?? today, today: today), help: Copy.Projects.dateChipHelp) {
            pickerOpen = true
        }
        .disabled(blocked)
        .popover(isPresented: $pickerOpen, arrowEdge: .bottom) {
            DatePicker("", selection: Binding(get: { (day ?? today).date(in: .autoupdatingCurrent) },
                                              set: { picked in
                                                  day = ISODay.today(now: picked)
                                                  pickerOpen = false
                                              }),
                       in: ...Date(), displayedComponents: .date)
                .labelsHidden()
                .datePickerStyle(.graphical)
                .padding(CicadaTheme.spacingMD)
        }
    }

    private func submit(_ status: String) {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty, !saving, !blocked else { return }
        saving = true
        let chosen = day
        Task {
            let answer = await save(words, status, chosen?.description)
            saving = false
            // A failure keeps the words in the field; the toast said why (R-PP19).
            guard let answer, let claimId = answer.claimId else { return }
            text = ""
            day = nil
            logged = (ProjectLogWords.confirmation(projectName, answer: answer, sentDay: chosen != nil, today: today), claimId)
            try? await Task.sleep(for: .seconds(CicadaTiming.undoWindow))
            if logged?.claimId == claimId { logged = nil }
        }
    }
}
