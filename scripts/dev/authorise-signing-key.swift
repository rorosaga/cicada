// authorise-signing-key — let codesign use exactly one private key without a dialog: set that key's partition list
// in one keychain, the way `security set-key-partition-list` does, but naming the key by its application label.
//
//   authorise-signing-key <keychain path> <application label: 40 hex digits> <partition ids, comma-separated>
//
// Why it exists (2026-10-15): `security set-key-partition-list` can only pick keys by text. `security import` labels
// every private key it imports "Imported Private Key" — only the certificate is labelled "Cicada Local" — so
// `-l "Cicada Local"` matched no key at all, and `-l "Imported Private Key"` would rewrite the partition list of every
// other key ever imported into the login keychain. The one attribute that names a key exactly is its application
// label, the SHA-1 of its public key (the keychain records it on the certificate as "hpky"), and it is binary: `-a`
// takes text and cannot match it. Renaming the key first is no way out either: changing any attribute of the key is an
// access to it, and macOS asks in a dialog. So this is a port of security's own `keychain_set_partition_list`
// (Apple's SecurityTool, keychain_find.c), the same calls in the same order, with the match by application label:
//   unlock the keychain with its password → find the one private key with that label, in that keychain only →
//   copy its access → rewrite each partition_id ACL entry's description to the hex of the XML plist
//   {"Partitions": [...]}, keeping its applications and prompt → SecKeychainItemSetAccessWithPassword.
// Like security, a key with no partition_id entry is left as it is: nothing restricts it by partition.
// It reads no key material and touches no other item.
//
// The password: asked on the terminal ("password to unlock <keychain>: "), as security asks. CICADA_KEYCHAIN_PASSWORD
// is for tests on a scratch keychain only.
//
// Built and run by scripts/dev/make-signing-identity.sh (step 2/3). Exit status: 0 done, 2 usage, 3 keychain or
// password, 4 search, 5 no such key or more than one, 6 reading or writing its access failed.
import Darwin
import Foundation
import Security

// SecKeychainItemSetAccessWithPassword is what security itself calls: exported by Security.framework (it is in the
// SDK's Security.tbd) but declared only in a private header, so it is looked up by name.
typealias SetAccessWithPassword = @convention(c) (SecKeychainItem, SecAccess, UInt32, UnsafeRawPointer) -> OSStatus

func message(_ status: OSStatus) -> String {
    (SecCopyErrorMessageString(status, nil) as String?) ?? "OSStatus \(status)"
}

func die(_ code: Int32, _ text: String) -> Never {
    FileHandle.standardError.write(Data(("authorise-signing-key: " + text + "\n").utf8))
    exit(code)
}

func hexBytes(_ hex: String) -> Data? {
    guard hex.count % 2 == 0, hex.allSatisfy(\.isHexDigit) else { return nil }
    var data = Data()
    var at = hex.startIndex
    while at < hex.endIndex {
        let next = hex.index(at, offsetBy: 2)
        data.append(UInt8(hex[at..<next], radix: 16)!)
        at = next
    }
    return data
}

// The partition IDs an ACL description holds, or nil when it is not the hex of a {"Partitions": [...]} plist.
func partitions(of description: String) -> [String]? {
    guard let data = hexBytes(description),
          let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
    else { return nil }
    return plist["Partitions"] as? [String]
}

let args = CommandLine.arguments
guard args.count == 4 else { die(2, "usage: authorise-signing-key <keychain> <application-label-hex> <partition-ids>") }
let (path, labelHex, partitionList) = (args[1], args[2], args[3])
guard labelHex.count == 40, let appLabel = hexBytes(labelHex) else {
    die(2, "the application label must be 40 hex digits: \(labelHex)")
}
let wanted = partitionList.components(separatedBy: ",")
guard !partitionList.isEmpty, !wanted.contains(where: \.isEmpty) else { die(2, "bad partition list: \(partitionList)") }

var opened: SecKeychain?
var status = SecKeychainOpen(path, &opened)
guard status == errSecSuccess, let keychain = opened else { die(3, "cannot open \(path): \(message(status))") }
var keychainStatus = SecKeychainStatus()
status = SecKeychainGetStatus(keychain, &keychainStatus)   // SecKeychainOpen succeeds on a missing file; this does not
guard status == errSecSuccess else { die(3, "cannot read \(path): \(message(status))") }

var password: [CChar]
if let given = ProcessInfo.processInfo.environment["CICADA_KEYCHAIN_PASSWORD"], !given.isEmpty {
    password = Array(given.utf8CString)
} else {
    var buffer = [CChar](repeating: 0, count: 1024)
    guard readpassphrase("password to unlock \(path): ", &buffer, buffer.count, RPP_REQUIRE_TTY) != nil else {
        die(3, "no terminal to ask the keychain password on — run it at the keyboard")
    }
    password = buffer
}
defer { for i in password.indices { password[i] = 0 } }
let passwordLength = UInt32(strlen(password))

// security unlocks with the password first, since it is about to read ACLs; so does this.
status = SecKeychainUnlock(keychain, passwordLength, password, true)
guard status == errSecSuccess else { die(3, "unlocking \(path): \(message(status))") }

let query: [String: Any] = [
    kSecClass as String: kSecClassKey,
    kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
    kSecAttrApplicationLabel as String: appLabel,
    kSecMatchSearchList as String: [keychain],
    kSecMatchLimit as String: kSecMatchLimitAll,
    kSecReturnRef as String: true,
    kSecReturnAttributes as String: true,
]
var found: CFTypeRef?
status = SecItemCopyMatching(query as CFDictionary, &found)
let rows: [[String: Any]]
if status == errSecItemNotFound {
    rows = []
} else if status == errSecSuccess {
    rows = found as? [[String: Any]] ?? []
} else {
    die(4, "searching \(path) failed: \(message(status))")
}
guard rows.count == 1, let ref = rows[0][kSecValueRef as String] else {
    die(5, rows.isEmpty
        ? "no private key in \(path) has the application label \(labelHex)"
        : "\(rows.count) private keys in \(path) have the application label \(labelHex); refusing to pick one")
}
let item = ref as! SecKeychainItem
let keyLabel = rows[0][kSecAttrLabel as String] as? String ?? ""

var access: SecAccess?
status = SecKeychainItemCopyAccess(item, &access)
guard status == errSecSuccess, let itemAccess = access else { die(6, "reading the key's access: \(message(status))") }
var aclList: CFArray?
status = SecAccessCopyACLList(itemAccess, &aclList)
guard status == errSecSuccess else { die(6, "reading the key's access list: \(message(status))") }

let plist = try! PropertyListSerialization.data(fromPropertyList: ["Partitions": wanted], format: .xml, options: 0)
let description = plist.map { String(format: "%02x", $0) }.joined()
var before: [[String]] = []
for acl in (aclList as? [SecACL]) ?? [] {
    let authorizations = SecACLCopyAuthorizations(acl) as? [String] ?? []
    guard authorizations.contains(kSecACLAuthorizationPartitionID as String) else { continue }
    var applications: CFArray?
    var current: CFString?
    var prompt = SecKeychainPromptSelector()
    status = SecACLCopyContents(acl, &applications, &current, &prompt)
    guard status == errSecSuccess else { die(6, "reading the key's partition list: \(message(status))") }
    before.append(partitions(of: (current as String?) ?? "") ?? ["<unreadable>"])
    status = SecACLSetContents(acl, applications, description as CFString, prompt)
    guard status == errSecSuccess else { die(6, "setting the key's partition list: \(message(status))") }
}

if before.isEmpty {
    print("the key \"\(keyLabel)\" (\(labelHex)) has no partition list; nothing restricts it by partition — left as it is")
    exit(0)
}
guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "SecKeychainItemSetAccessWithPassword") else {
    die(6, "this macOS has no SecKeychainItemSetAccessWithPassword")   // RTLD_DEFAULT is (void *)-2 on Darwin
}
let setAccess = unsafeBitCast(symbol, to: SetAccessWithPassword.self)
status = password.withUnsafeBytes { setAccess(item, itemAccess, passwordLength, $0.baseAddress!) }
guard status == errSecSuccess else { die(6, "saving the key's access: \(message(status))") }
let was = before.map { $0.joined(separator: ",") }.joined(separator: " ; ")
print("authorised the key \"\(keyLabel)\" (\(labelHex)): partition list \(was) -> \(partitionList)")
