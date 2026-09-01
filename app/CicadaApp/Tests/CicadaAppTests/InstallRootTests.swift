import XCTest
@testable import CicadaApp

/// G88 — `BackendProcess.installRoot()`'s resolution order. Before this fix,
/// an installed `~/Applications/Cicada.app` always fell through to the
/// `~/cicada` heuristic, which happens to exist on the dev machine (with only
/// a bare `memory/` inside) and so resolved *plausibly but wrongly* instead
/// of failing loudly — feeding a bad path into the Connect page's
/// copy-pasteable MCP commands. `bundle.sh` now stamps the checkout path
/// that produced the bundle into Info.plist as `CicadaRepoRoot`; these tests
/// exercise the resulting three-rung ladder without touching a real
/// Bundle/FileManager.
final class InstallRootTests: XCTestCase {

    private let installedBundlePath = "/Users/x/Applications/Cicada.app"
    private let devBundlePath = "/Users/x/repo/app/CicadaApp/.build/debug/Cicada.app"
    private let derivedDataBundlePath =
        "/Users/x/Library/Developer/Xcode/DerivedData/CicadaApp-abc/Build/Products/Debug/Cicada.app"

    // MARK: - Rung 1: stamped CicadaRepoRoot, present and on disk

    func testStampedRootWinsWhenItExistsOnDisk() {
        let root = BackendProcess.installRoot(
            bundlePath: installedBundlePath,
            stampedRepoRoot: "/Users/x/repo",
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { $0 == "/Users/x/repo" }
        )
        XCTAssertEqual(root.path, "/Users/x/repo")
    }

    func testStampedRootWinsEvenForAnInstalledBundleThatLooksLikeADevBuild() {
        // The .build/DerivedData sniff only applies to the fallback rungs —
        // a valid stamp always wins first, regardless of bundle path shape.
        let root = BackendProcess.installRoot(
            bundlePath: devBundlePath,
            stampedRepoRoot: "/Users/x/other-checkout",
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { $0 == "/Users/x/other-checkout" }
        )
        XCTAssertEqual(root.path, "/Users/x/other-checkout")
    }

    // MARK: - Rung 1 miss: stamp present but stale (repo moved, not rebuilt)

    func testStaleStampFallsThroughToTheHeuristicInsteadOfPointingAtNothing() {
        let root = BackendProcess.installRoot(
            bundlePath: installedBundlePath,
            stampedRepoRoot: "/Users/x/moved-away",
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { _ in false } // nothing exists — stamp is stale
        )
        XCTAssertEqual(root.path, "/Users/x/cicada", "installed bundle, no valid stamp -> ~/cicada")
    }

    func testEmptyStampIsTreatedAsAbsent() {
        let root = BackendProcess.installRoot(
            bundlePath: installedBundlePath,
            stampedRepoRoot: "",
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { _ in true }
        )
        XCTAssertEqual(root.path, "/Users/x/cicada")
    }

    // MARK: - Rung 2: no stamp, dev build (.build / DerivedData) -> walk up for CLAUDE.md

    func testNoStampDevBuildWalksUpToFindCLAUDEmd() {
        let root = BackendProcess.installRoot(
            bundlePath: devBundlePath,
            stampedRepoRoot: nil,
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { $0 == "/Users/x/repo/CLAUDE.md" }
        )
        XCTAssertEqual(root.path, "/Users/x/repo")
    }

    func testNoStampDerivedDataBuildFindsCLAUDEmdWhenAnAncestorHasIt() {
        // Contrived but exercises the same walk-up machinery as the .build
        // case: if some ancestor of the bundle path happens to carry
        // CLAUDE.md, the walk finds it before exhausting.
        let root = BackendProcess.installRoot(
            bundlePath: derivedDataBundlePath,
            stampedRepoRoot: nil,
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { $0 == "/Users/x/Library/Developer/Xcode/CLAUDE.md" }
        )
        XCTAssertEqual(root.path, "/Users/x/Library/Developer/Xcode")
    }

    func testNoStampDerivedDataBuildWithNoCLAUDEmdAnywhereFallsBackToInjectedHome() {
        // The realistic case: DerivedData lives under
        // ~/Library/Developer/Xcode/DerivedData, which has no ancestor
        // relationship to the checkout at all, so the walk always exhausts.
        // The fallback must use the INJECTED home directory, not silently
        // reach for the real FileManager.default one — otherwise this rung
        // is untestable and, worse, could leak the real user's home into a
        // path resolved for a fake bundle.
        let root = BackendProcess.installRoot(
            bundlePath: derivedDataBundlePath,
            stampedRepoRoot: nil,
            homeDirectory: URL(fileURLWithPath: "/Users/x"),
            pathExists: { _ in false }
        )
        XCTAssertEqual(root.path, "/Users/x/cicada")
    }

    // MARK: - Rung 3: no stamp, not a dev build shape -> ~/cicada

    func testNoStampInstalledBundleFallsBackToHomeCicada() {
        let root = BackendProcess.installRoot(
            bundlePath: installedBundlePath,
            stampedRepoRoot: nil,
            homeDirectory: URL(fileURLWithPath: "/Users/rorosaga"),
            pathExists: { _ in false }
        )
        XCTAssertEqual(root.path, "/Users/rorosaga/cicada")
    }
}
