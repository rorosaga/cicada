import Foundation

/// A country's calling code, for a connect sheet's phone step (owner 2026-10-29: *"with the country codes and such"*).
/// The person picks a country (flag, name, dial code — searchable, defaulting to this Mac's region) and types only the
/// national number; the sheet sends `+<dial><digits>`. Names come from the system locale, flags from the region's own
/// regional-indicator letters, so nothing here is fetched or kept. Pure values, testable without SwiftUI.
struct PhoneCountry: Identifiable, Hashable, Sendable {
    /// ISO 3166-1 alpha-2, upper case ("ES").
    let region: String
    /// The ITU calling code without its plus ("34").
    let dial: String

    var id: String { region }

    /// The region's flag, from its two regional-indicator symbols.
    var flag: String {
        region.unicodeScalars.compactMap { UnicodeScalar(0x1F1E6 + $0.value - 0x41) }.map(String.init).joined()
    }

    /// The country's name in the person's own language ("Spain", "España").
    func name(in locale: Locale = .current) -> String {
        locale.localizedString(forRegionCode: region) ?? region
    }

    var dialLabel: String { "+\(dial)" }

    /// The full international number the backend is handed: `+`, the dial code, the national digits (a leading
    /// trunk `0` dropped — it is never dialled from abroad).
    func international(_ national: String) -> String {
        var digits = Self.digits(national)
        if digits.hasPrefix("0") { digits.removeFirst() }
        return "+\(dial)\(digits)"
    }

    // MARK: - The list

    /// Every region with a calling code, sorted by its name in `locale`.
    static func all(locale: Locale = .current) -> [PhoneCountry] {
        table.sorted { $0.name(in: locale).localizedCaseInsensitiveCompare($1.name(in: locale)) == .orderedAscending }
    }

    /// The Mac's own region, else the United States — so most people never open the list.
    static func `default`(region: String? = Locale.current.region?.identifier) -> PhoneCountry {
        let code = (region ?? "").uppercased()
        return table.first { $0.region == code } ?? table.first { $0.region == "US" }!
    }

    /// Matches a name (any word's start, accents ignored), a region code, or a dial code with or without its plus.
    static func search(_ query: String, in list: [PhoneCountry], locale: Locale = .current) -> [PhoneCountry] {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return list }
        let dialQuery = q.hasPrefix("+") ? String(q.dropFirst()) : q
        if !dialQuery.isEmpty, dialQuery.allSatisfy(\.isNumber) {
            return list.filter { $0.dial.hasPrefix(dialQuery) }
        }
        let folded = q.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: locale)
        return list.filter { country in
            if country.region.caseInsensitiveCompare(q) == .orderedSame { return true }
            let name = country.name(in: locale).folding(options: [.caseInsensitive, .diacriticInsensitive], locale: locale)
            return name.hasPrefix(folded) || name.split(whereSeparator: { !$0.isLetter }).contains { $0.hasPrefix(folded) }
        }
    }

    // MARK: - The national number

    static func digits(_ text: String) -> String { String(text.filter(\.isASCIIDigit)) }

    /// Light formatting while typing: digits only, in groups of three ("612 345 678"); at most 15 digits (E.164).
    static func formatNational(_ text: String) -> String {
        let digits = String(Self.digits(text).prefix(15))
        var out = ""
        for (i, c) in digits.enumerated() {
            if i > 0, i % 3 == 0 { out.append(" ") }
            out.append(c)
        }
        return out
    }

    /// Enough digits to be a phone number at all; the backend and Telegram judge the rest.
    static func plausible(_ national: String) -> Bool { digits(national).count >= 4 }

    // MARK: - The table (ITU-T E.164 assignments by ISO region)

    static let table: [PhoneCountry] = raw.split(separator: " ").map { pair in
        let parts = pair.split(separator: ":")
        return PhoneCountry(region: String(parts[0]), dial: String(parts[1]))
    }

    private static let raw = """
    AD:376 AE:971 AF:93 AG:1268 AI:1264 AL:355 AM:374 AO:244 AR:54 AS:1684 AT:43 AU:61 AW:297 AX:358 AZ:994 \
    BA:387 BB:1246 BD:880 BE:32 BF:226 BG:359 BH:973 BI:257 BJ:229 BL:590 BM:1441 BN:673 BO:591 BQ:599 BR:55 \
    BS:1242 BT:975 BW:267 BY:375 BZ:501 CA:1 CC:61 CD:243 CF:236 CG:242 CH:41 CI:225 CK:682 CL:56 CM:237 CN:86 \
    CO:57 CR:506 CU:53 CV:238 CW:599 CX:61 CY:357 CZ:420 DE:49 DJ:253 DK:45 DM:1767 DO:1809 DZ:213 EC:593 EE:372 \
    EG:20 EH:212 ER:291 ES:34 ET:251 FI:358 FJ:679 FK:500 FM:691 FO:298 FR:33 GA:241 GB:44 GD:1473 GE:995 GF:594 \
    GG:44 GH:233 GI:350 GL:299 GM:220 GN:224 GP:590 GQ:240 GR:30 GT:502 GU:1671 GW:245 GY:592 HK:852 HN:504 \
    HR:385 HT:509 HU:36 ID:62 IE:353 IL:972 IM:44 IN:91 IO:246 IQ:964 IR:98 IS:354 IT:39 JE:44 JM:1876 JO:962 \
    JP:81 KE:254 KG:996 KH:855 KI:686 KM:269 KN:1869 KP:850 KR:82 KW:965 KY:1345 KZ:7 LA:856 LB:961 LC:1758 \
    LI:423 LK:94 LR:231 LS:266 LT:370 LU:352 LV:371 LY:218 MA:212 MC:377 MD:373 ME:382 MF:590 MG:261 MH:692 \
    MK:389 ML:223 MM:95 MN:976 MO:853 MP:1670 MQ:596 MR:222 MS:1664 MT:356 MU:230 MV:960 MW:265 MX:52 MY:60 \
    MZ:258 NA:264 NC:687 NE:227 NF:672 NG:234 NI:505 NL:31 NO:47 NP:977 NR:674 NU:683 NZ:64 OM:968 PA:507 PE:51 \
    PF:689 PG:675 PH:63 PK:92 PL:48 PM:508 PR:1787 PS:970 PT:351 PW:680 PY:595 QA:974 RE:262 RO:40 RS:381 RU:7 \
    RW:250 SA:966 SB:677 SC:248 SD:249 SE:46 SG:65 SH:290 SI:386 SJ:47 SK:421 SL:232 SM:378 SN:221 SO:252 SR:597 \
    SS:211 ST:239 SV:503 SX:1721 SY:963 SZ:268 TC:1649 TD:235 TG:228 TH:66 TJ:992 TK:690 TL:670 TM:993 TN:216 \
    TO:676 TR:90 TT:1868 TV:688 TW:886 TZ:255 UA:380 UG:256 US:1 UY:598 UZ:998 VA:39 VC:1784 VE:58 VG:1284 \
    VI:1340 VN:84 VU:678 WF:681 WS:685 XK:383 YE:967 YT:262 ZA:27 ZM:260 ZW:263
    """
}

private extension Character {
    var isASCIIDigit: Bool { ("0"..."9").contains(self) }
}
