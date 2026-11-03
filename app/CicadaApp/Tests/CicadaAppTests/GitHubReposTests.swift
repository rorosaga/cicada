import XCTest
@testable import CicadaApp

/// G230 — repositories on the graph: the wire's shapes, the Sources panel's decisions and model, the repository card's
/// words. No network: the model runs on `Deps`, every date is passed in with its locale.
@MainActor
final class GitHubReposTests: XCTestCase {
    private let locale = Locale(identifier: "en_US_POSIX")
    private let today = ISODay(year: 2026, month: 11, day: 3)

    private func repo(_ full: String = "bob-example/alpha-project", project: RepoProject? = nil,
                      owned: Bool = true) -> RepoRow {
        RepoRow(id: 501, fullName: full, url: "https://github.com/\(full)", description: "Notes.",
                language: "Python", topics: ["notes"], owned: owned, project: project)
    }

    // MARK: - The wire

    func testTheListsAndTheCardDecodeFromTheBackendsShapes() throws {
        let lists = try JSONDecoder().decode(RepoLists.self, from: Data("""
        {"connected": true,
         "owned": [{"id": 501, "fullName": "bob-example/alpha-project", "url": "https://github.com/bob-example/alpha-project",
                    "private": true, "topics": [], "ownerKind": "User", "archived": false, "fork": false,
                    "starred": false, "owned": true, "added": false,
                    "project": {"project": "alpha", "name": "alpha", "how": "origin"}}],
         "starred": [{"id": 601, "fullName": "example-org/widget-kit", "starred": true,
                      "starredAt": "2026-09-12T08:30:00+00:00", "entityId": "widget-kit"}]}
        """.utf8))
        XCTAssertTrue(lists.connected)
        XCTAssertEqual(lists.owned.first?.isPrivate, true)
        XCTAssertEqual(lists.owned.first?.project?.isSettled, true)
        XCTAssertEqual(lists.starred.first?.url, "https://github.com/example-org/widget-kit")   // derived when absent
        let card = try JSONDecoder().decode(RepositoryDetail.self, from: Data("""
        {"id": 601, "fullName": "example-org/widget-kit", "url": "https://github.com/example-org/widget-kit",
         "entityId": "widget-kit", "ownerKind": "Organization",
         "readme": {"state": "fresh", "text": "# Widget Kit", "truncated": false, "path": "README.md",
                    "fetchedAt": "2026-11-02T10:00:00+00:00"}}
        """.utf8))
        XCTAssertEqual(card.repo.owner, "example-org")
        XCTAssertEqual(card.repo.name, "widget-kit")
        XCTAssertEqual(card.readme.state, "fresh")
        let bare = try JSONDecoder().decode(RepositoryDetail.self, from: Data(#"{"fullName": "a-b/c"}"#.utf8))
        XCTAssertEqual(bare.readme.state, "missing")
    }

    // MARK: - The Sources panel

    func testTheFieldTakesOnlyARepository() {
        let cases: [(String, String?)] = [
            ("https://github.com/example-org/widget-kit", "example-org/widget-kit"),
            ("https://github.com/example-org/widget-kit/tree/main", "example-org/widget-kit"),
            ("github.com/example-org/widget-kit.git", "example-org/widget-kit"),
            ("git@github.com:example-org/widget-kit.git", "example-org/widget-kit"),
            ("example-org/widget-kit", "example-org/widget-kit"),
            ("https://gitlab.com/example-org/widget-kit", nil),
            ("https://github.com/example-org", nil),
            ("https://user@github.com/example-org/widget-kit", nil),
            ("not a link", nil),
        ]
        for (text, want) in cases { XCTAssertEqual(GitHubReposLogic.repository(text), want, text) }
    }

    func testEachRepositoryOffersWhatTheRecordAllows() {
        XCTAssertEqual(GitHubReposLogic.offer(repo()), .make)
        XCTAssertEqual(GitHubReposLogic.offer(repo(project: RepoProject(project: "alpha", name: "Alpha", how: "name"))),
                       .link(id: "alpha", name: "Alpha"))
        XCTAssertEqual(GitHubReposLogic.offer(repo(project: RepoProject(project: "alpha", name: "Alpha", how: "linked"))),
                       .project(id: "alpha", name: "Alpha"))
        XCTAssertEqual(GitHubReposLogic.detail(repo()), "Python · Notes.")
    }

    func testTheModelAddsMakesAProjectAndSaysWhatHappened() async {
        var added: [String] = []
        var projects: [(String, String?)] = []
        var loads = 0
        let model = GitHubReposModel(deps: .init(
            fetch: { loads += 1; return RepoLists(connected: true, owned: [self.repo()]) },
            add: { added.append($0); return RepoAddResult(entityId: "widget-kit", fullName: $0, created: true) },
            project: { projects.append(($0, $1)); return RepoProjectResult(project: "alpha-project", created: true) }))
        await model.load()
        XCTAssertEqual(model.lists.owned.count, 1)
        let refused = await model.add("https://example.com/x")
        XCTAssertFalse(refused)
        XCTAssertEqual(model.note, Copy.GitHub.notALink)
        XCTAssertTrue(added.isEmpty)                      // refused before any request
        let landed = await model.add("https://github.com/example-org/widget-kit/issues")
        XCTAssertTrue(landed)
        XCTAssertEqual(added, ["example-org/widget-kit"])
        XCTAssertEqual(model.note, Copy.GitHub.added("example-org/widget-kit"))
        await model.project(repo(), link: nil)
        XCTAssertEqual(projects.first?.0, "bob-example/alpha-project")
        XCTAssertNil(projects.first?.1)
        XCTAssertEqual(model.note, Copy.GitHub.started("alpha-project"))
        XCTAssertEqual(loads, 3)                          // read again after each write
    }

    func testARefusalKeepsTheServersSentence() async {
        let model = GitHubReposModel(deps: .init(
            fetch: { RepoLists() },
            add: { _ in throw APIError.httpError(404, #"{"detail": "GitHub has no repository there."}"#) },
            project: { _, _ in RepoProjectResult(project: "", created: false) }))
        let landed = await model.add("example-org/gone")
        XCTAssertFalse(landed)
        XCTAssertEqual(model.note, "GitHub has no repository there.")
    }

    /// Owner 2026-11-03: "i'd rather it said 'Add as a project'". One of the person's own repositories — a row, or a
    /// pasted link to it — has one action, the make-project route; only anyone else's is added as a page.
    func testYourOwnRepositoryIsAddedAsAProjectAndAnyoneElsesAsAPage() async {
        XCTAssertEqual(Copy.GitHub.addAsProject, "Add as a project")
        let fresh = repo("bob-example/alpha-project")
        let named = repo("bob-example/beta-notes", project: RepoProject(project: "beta", name: "Beta", how: "name"))
        let settled = repo("bob-example/gamma", project: RepoProject(project: "gamma", name: "Gamma", how: "origin"))
        let lists = RepoLists(connected: true, owned: [fresh, named, settled])
        XCTAssertEqual(GitHubReposLogic.owned("https://github.com/Bob-Example/alpha-project/issues", in: lists)?.fullName,
                       "bob-example/alpha-project")
        XCTAssertNil(GitHubReposLogic.owned("example-org/widget-kit", in: lists))
        XCTAssertNil(GitHubReposLogic.owned("bob-example/alpha-project", in: RepoLists()))   // before a sync

        var added: [String] = []
        var projects: [(String, String?)] = []
        let model = GitHubReposModel(deps: .init(
            fetch: { lists },
            add: { added.append($0); return RepoAddResult(entityId: "widget-kit", fullName: $0, created: true) },
            project: { projects.append(($0, $1)); return RepoProjectResult(project: $1 ?? "alpha-project",
                                                                           created: $1 == nil) }))
        await model.load()
        let made = await model.submit("github.com/bob-example/alpha-project")
        XCTAssertTrue(made)
        XCTAssertEqual(projects.last?.0, "bob-example/alpha-project")
        XCTAssertNil(projects.last?.1)
        XCTAssertEqual(model.note, Copy.GitHub.started("alpha-project"))
        let linked = await model.submit("bob-example/beta-notes")
        XCTAssertTrue(linked)
        XCTAssertEqual(projects.last?.1, "beta")
        XCTAssertEqual(model.note, Copy.GitHub.linked("Beta"))
        let already = await model.submit("bob-example/gamma")
        XCTAssertFalse(already)
        XCTAssertEqual(projects.count, 2)                 // nothing sent for a project it already is
        XCTAssertEqual(model.note, Copy.GitHub.alreadyProject("Gamma"))
        XCTAssertTrue(added.isEmpty)                      // none of the person's own became a repository page
        let page = await model.submit("example-org/widget-kit")
        XCTAssertTrue(page)
        XCTAssertEqual(added, ["example-org/widget-kit"])
    }

    func testGitHubIsACatalogueAccountRoutedLikeTheTokenConnectors() {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        XCTAssertEqual(entries.first { $0.id == "github" }?.group, .accounts)
        XCTAssertTrue(ChannelActions.connectorChannels.contains("github"))
        XCTAssertTrue(SourceCatalog.signInChannels.contains("github"))
        XCTAssertEqual(OriginIconography.logoName(for: "github-starred"), "github")
        XCTAssertEqual(OriginIconography.label(for: "github-starred"), "GitHub stars")
    }

    // MARK: - The repository card

    func testTheCardAsksForARepositoryOnlyWhereOneCanBe() {
        XCTAssertTrue(EntityDetailCard.wantsRepositoryDetail(type: .media, media: nil))
        XCTAssertTrue(EntityDetailCard.wantsRepositoryDetail(type: .project, media: nil))
        XCTAssertTrue(EntityDetailCard.wantsRepositoryDetail(
            type: .media, media: MediaBlock(url: "https://github.com/a-b/c", mediaType: "repository", kind: "repository")))
        XCTAssertFalse(EntityDetailCard.wantsRepositoryDetail(
            type: .media, media: MediaBlock(url: "https://example.com", mediaType: "url")))
        XCTAssertFalse(EntityDetailCard.wantsRepositoryDetail(type: .person, media: nil))
    }

    func testTheCardSaysWhatThePersonDidAndWhichFlagsHold() {
        var r = repo()
        r.starred = true
        r.starredAt = "2026-09-12T08:30:00+00:00"
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), "You starred it Sep 12")
        r.starred = false
        r.unstarredOn = "2026-10-30"
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), "No longer starred since Oct 30")
        r.unstarredOn = nil
        r.added = true
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), Copy.GitHub.youAdded)
        r.isPrivate = true
        r.archived = true
        XCTAssertEqual(RepositoryText.flags(r), ["Private", "Archived"])
        r.topics = ["a", "b", "c", "d", "e", "f", "g"]
        XCTAssertEqual(RepositoryText.topics(r).shown.count, 5)
        XCTAssertEqual(RepositoryText.topics(r).more, 2)
        XCTAssertEqual(RepositoryText.byline(r), "bob-example · Python")
    }

    func testAKeptSourceSaysItIsReadThroughItsAPI() {
        let source = PageBlocks.Source(ref: "https://github.com/example-org/widget-kit", kind: "url", label: nil,
                                       linkKind: "website", state: "kept", site: "github.com", checkedAt: nil,
                                       addedBy: "user", iconSite: nil)
        XCTAssertEqual(PageWords.state(source, today: today, locale: locale), Copy.Pages.kept)
    }

    func testTheReadmeReadsAsCleanLines() {
        let lines = RepositoryText.lines("# Widget Kit\n\n\n\nA **small** kit of `widgets`.\n\n## Install\n\n```\n"
                                         + "pip install widget-kit\n```\n- one\n* two\n---\n")
        XCTAssertEqual(lines, [
            .heading("Widget Kit", level: 1), .blank, .text("A small kit of widgets."), .blank,
            .heading("Install", level: 2), .blank, .text("pip install widget-kit"), .bullet("one"), .bullet("two"),
        ])
        XCTAssertEqual(RepositoryText.readmeWords(RepositoryReadme(state: "none")), Copy.GitHub.readmeNone)
        XCTAssertEqual(RepositoryText.readmeWords(RepositoryReadme(state: "missing")), Copy.GitHub.readmeMissing)
        XCTAssertNil(RepositoryText.readmeWords(RepositoryReadme(state: "fresh", text: "Hi")))
    }
}
