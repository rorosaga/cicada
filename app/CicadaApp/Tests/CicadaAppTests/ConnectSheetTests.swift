import XCTest
@testable import CicadaApp

/// The connect sheets' shape (DESIGN_RULES §9, 2026-10-29): the country picker's values, the one-time code's filter,
/// one primary per connector step, and the Telegram sheet's single "Done" only once connected.
final class ConnectSheetTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testTheDefaultCountryIsTheMacsRegion() {
        XCTAssertEqual(PhoneCountry.default(region: "ES").dial, "34")
        XCTAssertEqual(PhoneCountry.default(region: "pe").region, "PE")
        XCTAssertEqual(PhoneCountry.default(region: nil).region, "US")
        XCTAssertEqual(PhoneCountry.default(region: "ZZ").region, "US")
    }

    func testEveryRegionIsUniqueWithANameAndAFlag() {
        let regions = PhoneCountry.table.map(\.region)
        XCTAssertEqual(Set(regions).count, regions.count)
        XCTAssertGreaterThan(regions.count, 230)
        for country in PhoneCountry.table {
            XCTAssertEqual(country.region.count, 2, country.region)
            XCTAssertFalse(country.dial.isEmpty || !country.dial.allSatisfy(\.isNumber), country.region)
            XCTAssertNotEqual(country.name(in: en), "", country.region)
        }
        XCTAssertEqual(PhoneCountry.default(region: "ES").flag, "🇪🇸")
    }

    func testTheNumberSentIsInternationalWithNoTrunkZero() {
        let spain = PhoneCountry.default(region: "ES")
        XCTAssertEqual(spain.international("612 345 678"), "+34612345678")
        let uk = PhoneCountry.default(region: "GB")
        XCTAssertEqual(uk.international("07700 900123"), "+447700900123")
    }

    func testTheNationalNumberIsLightlyGrouped() {
        XCTAssertEqual(PhoneCountry.formatNational("612345678"), "612 345 678")
        XCTAssertEqual(PhoneCountry.formatNational("+34 (612)-34"), "346 123 4")
        XCTAssertEqual(PhoneCountry.formatNational(String(repeating: "9", count: 20)).filter(\.isNumber).count, 15)
        XCTAssertFalse(PhoneCountry.plausible("12"))
        XCTAssertTrue(PhoneCountry.plausible("612 3"))
    }

    func testSearchFindsANameACodeOrADialCode() {
        let all = PhoneCountry.all(locale: en)
        XCTAssertTrue(PhoneCountry.search("spa", in: all, locale: en).contains { $0.region == "ES" })
        XCTAssertTrue(PhoneCountry.search("kingdom", in: all, locale: en).contains { $0.region == "GB" })
        XCTAssertTrue(PhoneCountry.search("es", in: all, locale: en).contains { $0.region == "ES" })   // ES by its code
        XCTAssertEqual(Set(PhoneCountry.search("+44", in: all, locale: en).map(\.region)), ["GB", "GG", "IM", "JE"])
        XCTAssertEqual(PhoneCountry.search("", in: all, locale: en).count, all.count)
        XCTAssertTrue(PhoneCountry.search("cote", in: all, locale: en).contains { $0.region == "CI" })   // accents folded
    }

    func testTheCodeFieldKeepsOnlyDigitsUpToItsLength() {
        XCTAssertEqual(OneTimeCodeField.accept("12a34", length: 5), "1234")
        XCTAssertEqual(OneTimeCodeField.accept("Code: 12345 678", length: 5), "12345")
        XCTAssertEqual(OneTimeCodeField.telegramLength, 5)
    }

    func testAConnectorStepHasOnePrimary() {
        func status(tier: Int?, oauth: Bool, present: Bool) -> ConnectorStatus {
            ConnectorStatus(id: "x", label: "X", connected: false,
                            fields: [ConnectorField(name: "token", label: "Token", secret: true, present: present)],
                            lastSync: nil, lastError: nil, detail: nil, loginMode: oauth ? "oauth" : "credentials",
                            tier: tier)
        }
        XCTAssertEqual(ConnectorSetupState.primaryAction(status(tier: 2, oauth: false, present: false), draftsEmpty: true),
                       .connect)
        XCTAssertEqual(ConnectorSetupState.primaryAction(status(tier: nil, oauth: true, present: false), draftsEmpty: false),
                       .saveKeys)
        XCTAssertEqual(ConnectorSetupState.primaryAction(status(tier: nil, oauth: true, present: true), draftsEmpty: true),
                       .authorize)
        // Keys saved but new ones typed: saving them is the one action, authorizing comes after.
        XCTAssertEqual(ConnectorSetupState.primaryAction(status(tier: nil, oauth: true, present: true), draftsEmpty: false),
                       .saveKeys)
    }

    /// The Telegram sheet draws no "Done" before it is connected, and no stacked prominent buttons.
    func testTheTelegramSheetSaysDoneOnlyWhenConnected() throws {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Settings/ChatSourceRows.swift")
        let text = try String(contentsOf: url, encoding: .utf8)
        let start = try XCTUnwrap(text.range(of: "struct TelegramPanel: View {"))
        let end = try XCTUnwrap(text.range(of: "private var chatList: some View", range: start.upperBound..<text.endIndex))
        let panel = String(text[start.upperBound..<end.lowerBound])
        XCTAssertEqual(panel.components(separatedBy: "Copy.Connect.done").count - 1, 1)
        XCTAssertFalse(panel.contains("ChatSheetFooter"))
        XCTAssertFalse(panel.contains(".borderedProminent"))
        let connected = try XCTUnwrap(panel.range(of: "private var connectedStep"))
        let signIn = try XCTUnwrap(panel.range(of: "private var signInStep"))
        let done = try XCTUnwrap(panel.range(of: "Copy.Connect.done"))
        XCTAssertTrue(done.lowerBound > connected.lowerBound && done.lowerBound < signIn.lowerBound)
    }
}
