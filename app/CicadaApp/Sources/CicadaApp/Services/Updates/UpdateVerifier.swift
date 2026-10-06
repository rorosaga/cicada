import CryptoKit
import Foundation

/// G182 phase 5 — what a downloaded update must prove before anything on disk changes: its size, its SHA-256 and an
/// Ed25519 signature over its exact bytes, made with the release key whose public half `bundle.sh` stamped into this
/// app's Info.plist (`CicadaUpdatePublicKey`). The signature is the trust; the hash and size catch a truncated or
/// swapped download early and in plainer words. No key, or a key that isn't 32 bytes, refuses every update — an
/// unsigned update is never installed.
enum UpdateVerifier {
    static let publicKeyInfoKey = "CicadaUpdatePublicKey"

    enum Failure: Error, Equatable {
        case noPublicKey
        case unreadable
        case wrongSize(expected: Int64, actual: Int64)
        case hashMismatch
        case badSignature

        /// A phrase that follows "Couldn't get the update ready: ".
        var message: String {
            switch self {
            case .noPublicKey: Copy.Updates.reasonNoKey
            case .unreadable: Copy.Updates.reasonUnreadable
            case .wrongSize: Copy.Updates.reasonWrongSize
            case .hashMismatch: Copy.Updates.reasonHashMismatch
            case .badSignature: Copy.Updates.reasonBadSignature
            }
        }
    }

    /// The public key from its Info.plist form: base64 of the raw 32 bytes.
    static func publicKey(base64: String?) throws -> Curve25519.Signing.PublicKey {
        guard let raw = base64?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty,
              let data = Data(base64Encoded: raw), data.count == 32,
              let key = try? Curve25519.Signing.PublicKey(rawRepresentation: data) else { throw Failure.noPublicKey }
        return key
    }

    /// Lower-case hex SHA-256 of `data`.
    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Checks the file at `file` against `manifest`, in order of cost: the key, the size, the hash, the signature.
    /// The file is memory-mapped, never copied into a buffer of its own.
    static func verify(file: URL, manifest: UpdateManifest, publicKeyBase64: String?) throws {
        let key = try publicKey(base64: publicKeyBase64)
        guard let data = try? Data(contentsOf: file, options: .alwaysMapped) else { throw Failure.unreadable }
        guard Int64(data.count) == manifest.size else {
            throw Failure.wrongSize(expected: manifest.size, actual: Int64(data.count))
        }
        guard sha256Hex(data) == manifest.sha256.trimmingCharacters(in: .whitespaces).lowercased() else {
            throw Failure.hashMismatch
        }
        guard let signature = Data(base64Encoded: manifest.signature.trimmingCharacters(in: .whitespacesAndNewlines)),
              signature.count == 64, key.isValidSignature(signature, for: data) else { throw Failure.badSignature }
    }
}
