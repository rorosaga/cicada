import SwiftUI

/// G132 phase 3b — Settings → Devices' *Relay*: the relay address (off by default; `PUT /sync/relay`), and on a computer
/// that holds no shared memory yet, *Join with a code* (`/sync/relay/join`: the code the other computer shows and its
/// relay's address, then the same six digits on both screens and a confirmation here). Existing patterns only: a
/// Settings row with Settings' native rounded fields below (DR-76, as *Where your memory lives*), a neutral button for
/// the act and a text button for the rare one (DR-40), copy in plain words (DR-59), the digits in mono because they
/// are compared (DR-19). No chevron, no fold, no new motion.
struct RelaySection: View {
    @State private var model = RelayModel()
    /// The master token's page (a server's client never pairs): the home pairs, a computer sharing nothing may join.
    let canManage: Bool
    @State private var pairing = false

    private var canJoin: Bool { canManage && model.canJoin }
    private var canPair: Bool { canManage && model.sharing }

    var body: some View {
        if model.shown || model.setting == nil {
            SettingsGroupCard { row }
                .task { await model.refresh() }
        }
    }

    private var row: some View {
        SettingsRow(.relay, title: Copy.Relay.title,
                    detail: (model.setting?.on ?? false) ? Copy.Relay.detailOn : Copy.Relay.detailOff) {
            EmptyView()
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Relay.addressTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    TextField(Copy.Relay.addressPlaceholder, text: $model.address)
                        .textFieldStyle(.roundedBorder)
                        .font(CicadaTheme.bodyFont)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    NeutralButton(title: Copy.Relay.save, size: .compact,
                                  isDisabled: model.busy || model.address.trimmingCharacters(in: .whitespaces).isEmpty) {
                        Task { await model.save() }
                    }
                    if model.setting?.on ?? false {
                        TextButton(title: Copy.Relay.turnOff, inline: true) { Task { await model.turnOff() } }
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if canPair, model.setting?.on ?? false {
                        NeutralButton(title: Copy.Relay.pairButton, systemImage: "qrcode", size: .compact) {
                            pairing = true
                        }
                    }
                }
                if let problem = model.problem { danger(problem) }
                if canJoin { joinForm }
            }
        }
        .task(id: model.join?.state) { await model.pollJoin() }
        .sheet(isPresented: $pairing) { RelayPairSheet { pairing = false } }
    }

    @ViewBuilder private var joinForm: some View {
        SettingsDivider()
        Text(Copy.Relay.joinTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
        caption(Copy.Relay.joinDetail)
        if let join = model.join, join.state != nil {
            if let digits = RelayRules.digits(join.sas), join.state == "confirm" {
                Text(digits)
                    .font(CicadaTheme.font(size: 28, weight: .semibold).monospacedDigit())
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityIdentifier("relay.join.digits")
                caption(Copy.Relay.compare)
                HStack(spacing: CicadaTheme.spacingSM) {
                    NeutralButton(title: Copy.Relay.joinConfirm, size: .compact) { Task { await model.confirmJoin() } }
                    TextButton(title: Copy.Relay.cancel, inline: true) { Task { await model.cancelJoin() } }
                }
            } else if let text = join.text, !text.isEmpty {
                caption(text)
                if RelayRules.finished(join.state), join.state != "done" {
                    TextButton(title: Copy.Relay.newCode, inline: true) { Task { await model.cancelJoin() } }
                }
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Relay.codeTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    TextField(Copy.Relay.codePlaceholder, text: $model.code)
                        .textFieldStyle(.roundedBorder)
                        .font(CicadaTheme.bodyFont.monospaced())
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Relay.addressTitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    TextField(Copy.Relay.addressPlaceholder, text: $model.joinRelay)
                        .textFieldStyle(.roundedBorder)
                        .font(CicadaTheme.bodyFont)
                }
            }
            NeutralButton(title: Copy.Relay.join, size: .compact,
                          isDisabled: model.busy || model.code.trimmingCharacters(in: .whitespaces).isEmpty
                              || model.joinRelay.trimmingCharacters(in: .whitespaces).isEmpty) {
                Task { await model.startJoin() }
            }
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func danger(_ text: String) -> some View {
        Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// The home's *Pair a computer through the relay*: the QR (v2) drawn here with Core Image, inside a ring (DR-9), beside
/// the code for typing (DR-19); then the name of what answered — and on the typed path the six digits both screens
/// show — with the one confirmation (DR-40); "Two devices answered this code" when a second one did. Closing while it
/// waits cancels the code.
struct RelayPairSheet: View {
    var onClose: () -> Void
    @State private var model = RelayPairModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(Copy.Relay.pairTitle).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let created = model.created {
                HStack(alignment: .center, spacing: CicadaTheme.spacingXL) {
                    PairingQRImage(payload: created.qr.json)
                        .frame(width: CicadaTheme.scaled(168), height: CicadaTheme.scaled(168))
                        .padding(CicadaTheme.spacingSM)
                        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(Color.white))
                        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                        .opacity(model.session?.state == "waiting" ? 1 : 0.3)
                        .accessibilityLabel(Copy.Relay.pairTitle)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        Text(created.code)
                            .font(CicadaTheme.font(size: 28, weight: .semibold).monospacedDigit())
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .textSelection(.enabled)
                        Text(created.qr.relay)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .textSelection(.enabled)
                    }
                }
                status
            } else if model.problem == nil {
                ProgressView().controlSize(.small)
            }
            if let problem = model.problem {
                Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                TextButton(title: RelayRules.finished(model.session?.state) ? Copy.Relay.close : Copy.Relay.cancel) {
                    Task { await model.cancel() }
                    onClose()
                }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .background(CicadaTheme.background)
        .task { await model.start() }
        .task(id: model.created?.session.id) { await model.poll() }
    }

    @ViewBuilder private var status: some View {
        switch model.session?.state {
        case "confirm":
            if let name = model.session?.name { line(Copy.Relay.asks(name)) }
            if let digits = RelayRules.digits(model.session?.sas) {
                Text(digits)
                    .font(CicadaTheme.font(size: 28, weight: .semibold).monospacedDigit())
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityIdentifier("relay.pair.digits")
                line(Copy.Relay.compare)
            }
            NeutralButton(title: model.session?.typed == true ? Copy.Relay.confirm : Copy.Relay.confirmScanned,
                          size: .compact, isDisabled: model.busy) { Task { await model.confirm() } }
        case "done": line(Copy.Relay.added)
        case "void": line(model.session?.text ?? Copy.Relay.voided)
        case "expired":
            line(Copy.Relay.expired)
            NeutralButton(title: Copy.Relay.newCode, size: .compact) { Task { await model.start() } }
        default: line(Copy.Relay.pairLead)
        }
    }

    private func line(_ text: String) -> some View {
        Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
