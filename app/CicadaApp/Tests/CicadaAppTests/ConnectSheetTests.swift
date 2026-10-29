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

    func testAnInternationalNumberRepicksTheCountry() throws {
        let us = PhoneCountry.default(region: "US")
        for typed in ["+34 612 345 678", "0034 612 345 678", "+34612345678"] {
            let (country, rest) = try XCTUnwrap(PhoneCountry.international(typed, preferring: us), typed)
            XCTAssertEqual(country.region, "ES", typed)
            XCTAssertEqual(PhoneCountry.digits(rest), "612345678", typed)
            // Composed from any country, never "+3434…".
            XCTAssertEqual(us.international(typed), "+34612345678", typed)
        }
        XCTAssertNil(PhoneCountry.international("612 345 678"))
        // A shared code keeps the current country; otherwise its main region; the longest code wins.
        let canada = PhoneCountry.default(region: "CA")
        XCTAssertEqual(PhoneCountry.international("+1 416 555 0100", preferring: canada)?.0.region, "CA")
        XCTAssertEqual(PhoneCountry.international("+1 212 555 0100")?.0.region, "US")
        XCTAssertEqual(PhoneCountry.international("+44 7700 900123")?.0.region, "GB")
        XCTAssertEqual(PhoneCountry.international("+1 268 555 0100")?.0.region, "AG")
        XCTAssertEqual(PhoneCountry.international("+351 912 345 678")?.0.region, "PT")
    }

    /// Typing "+34 612 345 678" one key at a time: the "+" survives until "34" names Spain, then the field holds the
    /// national number only. The same for "0034…" and for "+351…", whose first digits name no code.
    func testTypingAnInternationalNumberKeyByKey() {
        func type(_ text: String, from start: PhoneCountry) -> (PhoneCountry, String) {
            var country = start, field = ""
            for key in text {
                (country, field) = PhoneCountry.typing(field + String(key), country: country)
            }
            return (country, field)
        }
        let us = PhoneCountry.default(region: "US")
        for (text, region, number) in [("+34 612 345 678", "ES", "+34612345678"),
                                       ("0034612345678", "ES", "+34612345678"),
                                       ("+351 912 345 678", "PT", "+351912345678"),
                                       ("+44 7700 900123", "GB", "+447700900123")] {
            let (country, field) = type(text, from: us)
            XCTAssertEqual(country.region, region, text)
            XCTAssertFalse(field.contains("+"), text)
            XCTAssertEqual(country.international(field), number, text)
        }
        XCTAssertEqual(PhoneCountry.typing("+", country: us).1, "+")
        XCTAssertEqual(PhoneCountry.typing("+3", country: us).1, "+3")
        XCTAssertEqual(type("612345678", from: us).1, "612 345 678")
    }

    func testTheLeadingZeroIsKeptOnlyWhereItIsPartOfTheNumber() {
        XCTAssertEqual(PhoneCountry.default(region: "CI").international("07 01 02 03 04"), "+2250701020304")
        XCTAssertEqual(PhoneCountry.default(region: "BJ").international("01 97 00 00 00"), "+2290197000000")
        XCTAssertEqual(PhoneCountry.default(region: "CG").international("06 123 4567"), "+242061234567")
        XCTAssertEqual(PhoneCountry.default(region: "IT").international("06 1234 5678"), "+390612345678")
        XCTAssertEqual(PhoneCountry.default(region: "SM").international("0549 123456"), "+3780549123456")
        XCTAssertEqual(PhoneCountry.default(region: "VA").international("06 6982"), "+39066982")
        XCTAssertEqual(PhoneCountry.default(region: "IT").international("312 345 6789"), "+393123456789")
        // Elsewhere the zero is a trunk prefix.
        XCTAssertEqual(PhoneCountry.default(region: "GB").international("07700 900123"), "+447700900123")
        XCTAssertEqual(PhoneCountry.default(region: "FR").international("06 12 34 56 78"), "+33612345678")
    }

    func testTheNationalNumberIsLightlyGrouped() {
        XCTAssertEqual(PhoneCountry.formatNational("612345678"), "612 345 678")
        XCTAssertEqual(PhoneCountry.formatNational("(612)-34"), "612 34")
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
        XCTAssertEqual(OneTimeCodeField.defaultLength, 5)
    }

    @MainActor
    func testTheCodeFieldTakesTheLengthTelegramReported() async throws {
        let six = try JSONDecoder().decode(TelegramStatusAnswer.self,
                                             from: Data(#"{"state": "code_sent", "codeLength": 6}"#.utf8))
        XCTAssertEqual(six.codeLength, 6)
        let api = FakeChatSourcesAPI()
        api.telegramStatuses = [six]
        let model = TelegramChats(api: api)
        await model.refresh()
        XCTAssertEqual(model.codeLength, 6)
        api.telegramStatuses = [TelegramStatusAnswer(state: "code_sent")]
        await model.refresh()
        XCTAssertEqual(model.codeLength, 5)
    }

    /// One ⏎ can reach a field's submit and the default button: the second send is refused while the first is in
    /// flight, so Telegram is asked for one code.
    @MainActor
    func testOneReturnSendsThePhoneOnce() async {
        let api = FakeChatSourcesAPI()
        api.holdConnect = true
        let model = TelegramChats(api: api)
        // The two calls one Return makes: each spawns its task in the same turn, as the field's submit and the
        // default button do.
        let first = Task { await model.connect(phone: "+34612345678") }
        let second = Task { await model.connect(phone: "+34612345678") }
        while api.connectGate == nil { await Task.yield() }
        await second.value
        api.connectGate?.resume()
        await first.value
        XCTAssertEqual(api.telegramConnects, 1)
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
