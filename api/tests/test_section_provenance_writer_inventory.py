"""Pin every markdown writer call's declared G118 scope, without importing it.

Direct .frontmatter writes preserve guarded records; fresh literal frontmatter
has no links. Dynamic builders are explicitly uninstrumented (may preserve or
replace). The inventoried code remains responsible for that behavior; no blanket
coverage promise is inferred from an alias. A new call/expression needs review.
"""
import ast
import json
from pathlib import Path


def test_writer_calls_have_an_explicit_preserve_refresh_or_uninstrumented_disposition():
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / 'tests/fixtures/section_writer_inventory.json').read_text())
    actual = {}
    class Calls(ast.NodeVisitor):
        def __init__(self):
            self.scope, self.rows = [], []
        def visit_FunctionDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_Call(self, node):
            target = node.func
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'markdown_parser' and target.attr in ('write', 'write_new', 'write_document'):
                fm = node.args[1] if len(node.args) > 1 else None
                self.rows.append(( '.'.join(self.scope), target.attr, ast.unparse(fm) if fm else ''))
            self.generic_visit(node)
    for directory in ('services', 'routers'):
        for path in sorted((root / directory).glob('*.py')):
            visitor = Calls()
            visitor.visit(ast.parse(path.read_text()))
            if visitor.rows:
                actual[str(path.relative_to(root))] = visitor.rows
    assert actual == {path: [(row['function'], row['method'], row['frontmatter']) for row in rows]
                      for path, rows in expected.items()}
    modes = {'refresh_or_preserve', 'preserve_frontmatter_guarded', 'fresh_frontmatter_untracked', 'uninstrumented_guarded'}
    assert all(row['disposition'] in modes for rows in expected.values() for row in rows)
    assert all(row['disposition'] == 'refresh_or_preserve' for row in expected['services/conflict_resolver.py'])
    # skill_pages constructs its own frontmatter; source-page provenance cannot
    # be promised there. It is deliberately outside selected-input recording.
    assert all(row['disposition'] == 'uninstrumented_guarded' for row in expected['services/skill_pages.py'])
