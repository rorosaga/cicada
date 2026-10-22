import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

/// G212 — *Pair a device*: a one-time code from `POST /devices/pairing`, drawn here as a QR (CoreImage, correction
/// level M, inside a ring — never a shadow, DR-9) beside the code itself for typing (DR-19: it is copied, so mono), a
/// countdown, and a poll every 2 s until the other device redeems it (`POST /pair` on that device). Paired closes the
/// sheet; expired offers a new code; closing while it waits cancels the code (`DELETE /devices/pairing/{id}`). The
/// master token's alone — a server's client never shows the button (`DevicesPageModel.canManage`).
///
/// The address in the QR: none yet. `POST /pair` is served on the backend's own port, which binds 127.0.0.1 (G181);
/// the G135 listener's public address (`GET /remote/status`) does not serve it, so putting that address in the QR
/// would send the new device to a door that answers 404. Until the backend reports an overlay address for its own
/// port, the QR carries the code and the other device asks for the address — said in words under the code.
struct PairDeviceSheet: View {
    var onClose: () -> Void

    @State private var created: PairingCreated?
    @State private var state = "waiting"
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(Copy.DevicesPage.pairTitle).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let created {
                HStack(alignment: .center, spacing: CicadaTheme.spacingXL) {
                    PairingQRImage(payload: PairingPayload.json(created.qr))
                        .frame(width: CicadaTheme.scaled(168), height: CicadaTheme.scaled(168))
                        .padding(CicadaTheme.spacingSM)
                        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(Color.white))
                        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                        .opacity(state == "waiting" ? 1 : 0.3)
                        .accessibilityLabel(Copy.DevicesPage.pairTitle)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        Text(created.code)
                            .font(CicadaTheme.font(size: 28, weight: .semibold, design: .monospaced))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .textSelection(.enabled)
                        Text(Copy.DevicesPage.noAddress)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        if state == "waiting", let expires = created.pairing.expiresAt.flatMap(ISODate.parse) {
                            Text(Copy.DevicesPage.expires(expires))
                                .font(CicadaTheme.captionFont.monospacedDigit())
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        if state == "expired" {
                            Text(Copy.DevicesPage.expired)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                            NeutralButton(title: Copy.DevicesPage.newCode, size: .compact) { Task { await start() } }
                        }
                    }
                }
                Text(Copy.DevicesPage.pairHint)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else if problem == nil {
                ProgressView().controlSize(.small)
            }
            if let problem {
                Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                TextButton(title: Copy.DevicesPage.cancel) { close() }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .background(CicadaTheme.background)
        .task { await start() }
        .task(id: created?.pairing.id) { await poll() }
    }

    private func start() async {
        problem = nil
        state = "waiting"
        do {
            created = try await APIClient.shared.createPairing(url: nil)
        } catch {
            let answer = ConnectionModelText.detail(error)
            problem = answer?.code == 409 ? Copy.DevicesPage.tooMany : (answer?.text ?? error.localizedDescription)
        }
    }

    private func poll() async {
        guard let id = created?.pairing.id else { return }
        while !Task.isCancelled, state == "waiting" {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled, let answer = try? await APIClient.shared.pairingState(id) else { continue }
            state = answer.pairing.state
            if state == "paired" { onClose(); return }
        }
    }

    private func close() {
        if state == "waiting", let id = created?.pairing.id {
            Task { try? await APIClient.shared.cancelPairing(id) }
        }
        onClose()
    }
}

/// The QR's payload and address rule, pure (tested).
enum PairingPayload {
    /// Compact JSON `{"v":1,"url":…,"code":…}` with sorted keys, so the same code always draws the same QR.
    static func json(_ qr: PairingQR) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return (try? encoder.encode(qr)).flatMap { String(data: $0, encoding: .utf8) } ?? qr.code
    }

    /// The backend's address rule (https, or http to loopback only); anything else is no address.
    static func address(_ raw: String?) -> String? {
        guard let raw, let url = URL(string: raw), let host = url.host else { return nil }
        if url.scheme == "https" { return raw.hasSuffix("/") ? String(raw.dropLast()) : raw }
        if url.scheme == "http", ["127.0.0.1", "localhost", "::1"].contains(host) { return raw }
        return nil
    }
}

/// A QR drawn on this Mac with CoreImage — no service sees the code.
struct PairingQRImage: View {
    let payload: String

    var body: some View {
        if let image = Self.image(payload) {
            Image(nsImage: image).interpolation(.none).resizable().scaledToFit()
        } else {
            Image(systemName: "qrcode").resizable().scaledToFit().foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    static func image(_ payload: String) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(payload.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        let rep = NSCIImageRep(ciImage: output)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
    }
}
