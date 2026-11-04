import CryptoKit
import Foundation

/// Proposed ruling 55 (G81): a card's number as the keyed hash `phone_numbers.py` makes, computed here so no digit
/// crosses the wire (R-SR8 holds). `PhoneNumberKeysTests` pins this to the backend's own test vector.
enum PhoneNumberKeys {
    static func matchDigits(_ number: String) -> String? {
        let digits = number.filter { $0.isASCII && $0.isNumber }
        guard (7...15).contains(digits.count) else { return nil }
        return String(digits.suffix(9))
    }

    /// Ten lowercase letters: the first eight bytes of HMAC-SHA256(key, digits), big-endian, base 26, least digit first.
    static func tokenId(keyBase64: String, number: String) -> String? {
        guard let digits = matchDigits(number), let key = Data(base64Encoded: keyBase64) else { return nil }
        let mac = HMAC<SHA256>.authenticationCode(for: Data(digits.utf8), using: SymmetricKey(data: key))
        var value = Data(mac).prefix(8).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
        var letters = ""
        for _ in 0..<10 {
            letters.unicodeScalars.append(UnicodeScalar(UInt8(97 + value % 26)))
            value /= 26
        }
        return letters
    }

    static func keys(keyBase64: String?, numbers: [String]) -> [String] {
        guard let keyBase64 else { return [] }
        var seen = Set<String>()
        return numbers.compactMap { tokenId(keyBase64: keyBase64, number: $0) }.filter { seen.insert($0).inserted }
    }
}
