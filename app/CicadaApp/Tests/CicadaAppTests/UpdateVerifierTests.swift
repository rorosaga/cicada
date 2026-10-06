import CryptoKit
import XCTest
@testable import CicadaApp

/// G182 phase 5 — an update is installed only when its size, SHA-256 and Ed25519 signature all match, under the
/// public key stamped into the app. The key here is made fresh per test; nothing touches the network.
final class UpdateVerifierTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("UpdateVerifierTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: dir) }

    /// A file, its signed manifest, and the base64 public key that verifies it.
    static func signedFixture(in dir: URL, bytes: Data = Data((0..<4096).map { UInt8($0 % 251) }),
                              version: String = "0.3.1",
                              key: Curve25519.Signing.PrivateKey = .init()) throws -> (URL, UpdateManifest, String) {
        let file = dir.appendingPathComponent("Cicada-\(version).zip")
        try bytes.write(to: file)
        let signature = try key.signature(for: bytes)
        let manifest = UpdateManifest(
            version: version, url: URL(string: "https://example.com/Cicada-\(version).zip")!, size: Int64(bytes.count),
            sha256: UpdateVerifier.sha256Hex(bytes), signature: signature.base64EncodedString())
        return (file, manifest, key.publicKey.rawRepresentation.base64EncodedString())
    }

    func testACorrectlySignedFileVerifies() throws {
        let (file, manifest, key) = try Self.signedFixture(in: dir)
        XCTAssertNoThrow(try UpdateVerifier.verify(file: file, manifest: manifest, publicKeyBase64: key))
        // The hash is compared case-insensitively.
        let upper = UpdateManifest(version: manifest.version, url: manifest.url, size: manifest.size,
                                   sha256: manifest.sha256.uppercased(), signature: manifest.signature)
        XCTAssertNoThrow(try UpdateVerifier.verify(file: file, manifest: upper, publicKeyBase64: key))
    }

    func testAWrongSizeIsRefused() throws {
        let (file, m, key) = try Self.signedFixture(in: dir)
        let wrong = UpdateManifest(version: m.version, url: m.url, size: m.size + 1, sha256: m.sha256, signature: m.signature)
        XCTAssertThrowsError(try UpdateVerifier.verify(file: file, manifest: wrong, publicKeyBase64: key)) {
            XCTAssertEqual($0 as? UpdateVerifier.Failure, .wrongSize(expected: m.size + 1, actual: m.size))
        }
    }

    func testAWrongHashIsRefused() throws {
        let (file, m, key) = try Self.signedFixture(in: dir)
        let wrong = UpdateManifest(version: m.version, url: m.url, size: m.size,
                                   sha256: String(repeating: "0", count: 64), signature: m.signature)
        XCTAssertThrowsError(try UpdateVerifier.verify(file: file, manifest: wrong, publicKeyBase64: key)) {
            XCTAssertEqual($0 as? UpdateVerifier.Failure, .hashMismatch)
        }
    }

    func testASignatureFromAnotherKeyIsRefused() throws {
        let (file, m, _) = try Self.signedFixture(in: dir)
        let stranger = Curve25519.Signing.PrivateKey().publicKey.rawRepresentation.base64EncodedString()
        XCTAssertThrowsError(try UpdateVerifier.verify(file: file, manifest: m, publicKeyBase64: stranger)) {
            XCTAssertEqual($0 as? UpdateVerifier.Failure, .badSignature)
        }
    }

    func testATamperedFileWithAMatchingHashStillNeedsTheSignature() throws {
        // A swapped zip whose manifest was rewritten to its hash and size: only the signature catches it.
        let (_, m, key) = try Self.signedFixture(in: dir)
        let evil = Data(repeating: 7, count: 4096)
        let evilFile = dir.appendingPathComponent("evil.zip")
        try evil.write(to: evilFile)
        let forged = UpdateManifest(version: m.version, url: m.url, size: Int64(evil.count),
                                    sha256: UpdateVerifier.sha256Hex(evil), signature: m.signature)
        XCTAssertThrowsError(try UpdateVerifier.verify(file: evilFile, manifest: forged, publicKeyBase64: key)) {
            XCTAssertEqual($0 as? UpdateVerifier.Failure, .badSignature)
        }
    }

    func testAMalformedSignatureIsRefused() throws {
        let (file, m, key) = try Self.signedFixture(in: dir)
        for bad in ["", "not base64!", Data(repeating: 1, count: 63).base64EncodedString()] {
            let wrong = UpdateManifest(version: m.version, url: m.url, size: m.size, sha256: m.sha256, signature: bad)
            XCTAssertThrowsError(try UpdateVerifier.verify(file: file, manifest: wrong, publicKeyBase64: key)) {
                XCTAssertEqual($0 as? UpdateVerifier.Failure, .badSignature, bad)
            }
        }
    }

    func testAMissingOrInvalidPublicKeyRefusesEveryUpdate() throws {
        let (file, m, _) = try Self.signedFixture(in: dir)
        for key in [nil, "", "   ", "not base64", Data(repeating: 1, count: 31).base64EncodedString(),
                    Data(repeating: 1, count: 33).base64EncodedString()] as [String?] {
            XCTAssertThrowsError(try UpdateVerifier.verify(file: file, manifest: m, publicKeyBase64: key)) {
                XCTAssertEqual($0 as? UpdateVerifier.Failure, .noPublicKey, String(describing: key))
            }
        }
    }

    func testAMissingFileIsUnreadable() throws {
        let (_, m, key) = try Self.signedFixture(in: dir)
        XCTAssertThrowsError(try UpdateVerifier.verify(file: dir.appendingPathComponent("gone.zip"), manifest: m,
                                                       publicKeyBase64: key)) {
            XCTAssertEqual($0 as? UpdateVerifier.Failure, .unreadable)
        }
    }

    func testEveryFailureHasAPlainPhrase() {
        let all: [UpdateVerifier.Failure] = [.noPublicKey, .unreadable, .wrongSize(expected: 1, actual: 2), .hashMismatch,
                                             .badSignature]
        for f in all {
            XCTAssertFalse(f.message.isEmpty)
            XCTAssertFalse(f.message.hasSuffix("."), "a phrase, ended by the sentence it goes in")
        }
    }
}
