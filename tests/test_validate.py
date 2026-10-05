from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from scripts import validate as validator


SOURCE_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAMES = [f"sample-skill-{index:02d}" for index in range(1, 16)]
CONTRIBUTING_KEY_LINE = next(
    line
    for line in (SOURCE_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").splitlines()
    if "`disable-model-invocation`" in line
)


def numbered_lines(count: int, width: int = 1) -> str:
    return "".join(f"{'x' * width}\n" for _ in range(count))


UNSCOPED_BASH_FORMS = {
    "comment": "allowed-tools:\n  - Bash # everything\n",
    "flow": "allowed-tools: [Read,\n  Bash]\n",
    "folded": "allowed-tools: >\n  Bash\n",
    "repeated": "allowed-tools: Read\nallowed-tools: Bash\n",
}


def skill_text(name: str, total_lines: int, width: int = 1, extra_frontmatter: str = "") -> str:
    header = f'---\nname: {name}\ndescription: "Reusable sample skill."\nlicense: MIT\n{extra_frontmatter}---\n'
    return header + numbered_lines(total_lines - header.count("\n"), width)


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build_valid_repository()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_json(self, relative: str) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def write_json(self, relative: str, value: object) -> None:
        self.write(relative, json.dumps(value, indent=2) + "\n")

    def build_valid_repository(self) -> None:
        catalog_skills = {}
        route_skills = {}
        positive = {}
        for index, name in enumerate(SKILL_NAMES, start=1):
            description = f"Reusable sample skill number {index}."
            self.write(
                f"skills/{name}/SKILL.md",
                "\n".join(
                    [
                        "---",
                        f"name: {name}",
                        f'description: "{description}"',
                        "license: MIT",
                        "---",
                        "",
                        f"# Sample skill {index}",
                        "",
                    ]
                ),
            )
            catalog_skills[name] = {"path": f"skills/{name}"}
            keyword = f"route-token-{index:02d}-done"
            route_skills[name] = {
                "priority": "medium",
                "promptTriggers": {"keywords": [keyword], "intentPatterns": []},
                "fileTriggers": {"pathPatterns": [], "pathExclusions": []},
            }
            positive[f"please use {keyword}"] = [name]

        self.write("agents/helper.md", "---\nname: helper\ndescription: Sample helper agent.\n---\n# Helper\n")
        self.write("templates/CLAUDE.md", "# Agent rules\n")
        self.write("templates/AGENTS.md", "# Agent rules\n")
        self.write("hooks/merge-guard.py", "VALUE = 1\n")
        self.write("hooks/skill-usage-log.py", "VALUE = 1\n")
        source_hook = SOURCE_ROOT / "hooks" / "skill-activation.py"
        target_hook = self.root / "hooks" / "skill-activation.py"
        target_hook.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_hook, target_hook)

        self.write_json(
            "catalog.json",
            {
                "schemaVersion": 1,
                "name": "ai-skills-assembly",
                "displayName": "AI Skills Assembly",
                "surfaces": {
                    "skills": ["agents", "claude", "codex"],
                    "agents": ["claude", "codex"],
                    "outputStyles": ["claude"],
                },
                "skills": catalog_skills,
                "agents": {"helper": {"path": "agents/helper.md"}},
                "outputStyles": {},
                "profiles": {"default": {"skills": SKILL_NAMES, "agents": ["helper"], "outputStyles": []}},
                "routing": {
                    "registry": "routing/skill-rules.json",
                    "fixtures": "routing/routing-expectations.json",
                },
                "globalRules": {
                    "claude": "templates/CLAUDE.md",
                    "codex": "templates/AGENTS.md",
                },
                "hooks": {
                    "activation": "hooks/skill-activation.py",
                    "mergeGuard": "hooks/merge-guard.py",
                    "usage": "hooks/skill-usage-log.py",
                },
            },
        )
        self.write_json("routing/skill-rules.json", {"version": "1.0", "skills": route_skills})
        self.write_json(
            "routing/routing-expectations.json",
            {"version": "1.0", "positive": positive, "negative": ["an unrelated prompt"]},
        )

    def add_catalog_skill(self, name: str, include_in_default: bool = True) -> None:
        self.write(
            f"skills/{name}/SKILL.md",
            f'---\nname: {name}\ndescription: "Reusable extra skill."\nlicense: MIT\n---\n',
        )
        catalog = self.read_json("catalog.json")
        catalog["skills"][name] = {"path": f"skills/{name}"}
        if include_in_default:
            catalog["profiles"]["default"]["skills"].append(name)
        self.write_json("catalog.json", catalog)

        registry = self.read_json("routing/skill-rules.json")
        registry["skills"][name] = {
            "priority": "medium",
            "promptTriggers": {"keywords": ["extra-route-token"], "intentPatterns": []},
            "fileTriggers": {"pathPatterns": [], "pathExclusions": []},
        }
        self.write_json("routing/skill-rules.json", registry)
        fixtures = self.read_json("routing/routing-expectations.json")
        fixtures["positive"]["please use extra-route-token"] = [name]
        self.write_json("routing/routing-expectations.json", fixtures)

    def errors_for(self, check: str, denylist: Path | None = None) -> list[validator.Finding]:
        return [
            item
            for item in validator.validate(self.root, denylist)
            if item.check == check and item.severity == "error"
        ]

    def cap_paths(self) -> set[str]:
        return {item.path for item in self.errors_for("caps")}

    def write_agent(self, frontmatter: str) -> None:
        self.write("agents/helper.md", f"---\nname: helper\n{frontmatter}---\n# Helper\n")

    def outside_file(self, content: str) -> Path:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        path = Path(outside.name) / "denylist.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_repository_passes(self) -> None:
        self.assertEqual([], validator.validate(self.root))

    def test_python_compile_failure_is_reported(self) -> None:
        self.write("scripts/broken.py", "if True print('broken')\n")

        self.assertTrue(self.errors_for("python"))

    def test_catalog_rejects_path_escape(self) -> None:
        catalog = self.read_json("catalog.json")
        catalog["skills"][SKILL_NAMES[0]]["path"] = "../outside"
        self.write_json("catalog.json", catalog)

        self.assertTrue(self.errors_for("catalog"))

    def test_catalog_requires_canonical_repository_slug(self) -> None:
        cases = (
            (42, "name must be a string"),
            ("ai-skills", "name must be 'ai-skills-assembly'"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                catalog = self.read_json("catalog.json")
                catalog["name"] = value
                self.write_json("catalog.json", catalog)

                findings = self.errors_for("catalog")

                self.assertTrue(any(expected in item.message for item in findings))
                catalog["name"] = "ai-skills-assembly"
                self.write_json("catalog.json", catalog)

    def test_catalog_requires_canonical_display_name(self) -> None:
        cases = (
            ([], "displayName must be a string"),
            ("AI Skills", "displayName must be 'AI Skills Assembly'"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                catalog = self.read_json("catalog.json")
                catalog["displayName"] = value
                self.write_json("catalog.json", catalog)

                findings = self.errors_for("catalog")

                self.assertTrue(any(expected in item.message for item in findings))
                catalog["displayName"] = "AI Skills Assembly"
                self.write_json("catalog.json", catalog)

    def test_catalog_requires_skill_license(self) -> None:
        path = self.root / "skills" / SKILL_NAMES[0] / "SKILL.md"
        path.write_text(path.read_text(encoding="utf-8").replace("license: MIT\n", ""), encoding="utf-8")

        self.assertTrue(self.errors_for("catalog"))

    def test_catalog_validates_hook_paths(self) -> None:
        catalog = self.read_json("catalog.json")
        catalog["hooks"]["activation"] = "../outside.py"
        self.write_json("catalog.json", catalog)

        self.assertTrue(self.errors_for("catalog"))

    def test_catalog_path_maps_require_string_values(self) -> None:
        catalog = self.read_json("catalog.json")
        catalog["hooks"]["activation"] = {"path": "hooks/skill-activation.py"}
        self.write_json("catalog.json", catalog)

        findings = self.errors_for("catalog")
        self.assertTrue(any("must be a string path" in item.message for item in findings))

    def test_catalog_requires_global_rule_keys(self) -> None:
        catalog = self.read_json("catalog.json")
        del catalog["globalRules"]["codex"]
        self.write_json("catalog.json", catalog)

        findings = self.errors_for("catalog")
        self.assertTrue(any("globalRules is missing required keys" in item.message for item in findings))

    def test_catalog_requires_hook_keys(self) -> None:
        catalog = self.read_json("catalog.json")
        del catalog["hooks"]["usage"]
        self.write_json("catalog.json", catalog)

        findings = self.errors_for("catalog")
        self.assertTrue(any("hooks is missing required keys" in item.message for item in findings))

    def test_catalog_validates_every_profile(self) -> None:
        catalog = self.read_json("catalog.json")
        catalog["profiles"]["broken-profile"] = {"skills": ["missing-skill"], "agents": []}
        self.write_json("catalog.json", catalog)

        findings = self.errors_for("catalog")
        self.assertTrue(any("profiles.broken-profile.skills" in item.message for item in findings))

    def test_catalog_allows_default_profile_to_grow(self) -> None:
        self.add_catalog_skill("sample-skill-extra")

        self.assertEqual([], validator.validate(self.root))

    def test_default_profile_must_include_every_skill(self) -> None:
        self.add_catalog_skill("sample-skill-extra", include_in_default=False)

        findings = self.errors_for("catalog")
        self.assertTrue(any("default profile omits public skills" in item.message for item in findings))

    def test_stray_skill_directory_is_reported(self) -> None:
        self.write("skills/stray-skill/notes.txt", "not a skill\n")

        findings = self.errors_for("catalog")
        self.assertTrue(any("uncataloged skill directories" in item.message for item in findings))

    def test_routing_fixture_mismatch_is_reported(self) -> None:
        fixtures = self.read_json("routing/routing-expectations.json")
        first_prompt = next(iter(fixtures["positive"]))
        fixtures["positive"][first_prompt] = [SKILL_NAMES[1]]
        self.write_json("routing/routing-expectations.json", fixtures)

        self.assertTrue(self.errors_for("routing"))

    def test_missing_routing_rule_is_reported(self) -> None:
        registry = self.read_json("routing/skill-rules.json")
        missing = SKILL_NAMES[0]
        del registry["skills"][missing]
        self.write_json("routing/skill-rules.json", registry)
        fixtures = self.read_json("routing/routing-expectations.json")
        fixtures["positive"] = {
            prompt: expected
            for prompt, expected in fixtures["positive"].items()
            if missing not in expected
        }
        self.write_json("routing/routing-expectations.json", fixtures)

        findings = self.errors_for("routing")
        self.assertTrue(any("catalog skills lack routing rules" in item.message for item in findings))

    def test_listing_budget_overflow_is_reported(self) -> None:
        description = "x" * 240
        for name in SKILL_NAMES:
            path = self.root / "skills" / name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                next(line for line in text.splitlines() if line.startswith("description:")),
                f'description: "{description}"',
            )
            path.write_text(text, encoding="utf-8")

        self.assertFalse(self.errors_for("catalog"))
        self.assertTrue(self.errors_for("listing"))

    def test_listing_thresholds_match_the_caps(self) -> None:
        self.assertEqual((2_500, 3_000), (validator.LISTING_WARN_CHARS, validator.LISTING_FAIL_CHARS))

    def test_skill_description_bound_is_250_characters(self) -> None:
        path = self.root / "skills" / SKILL_NAMES[0] / "SKILL.md"
        original = path.read_text(encoding="utf-8")
        line = next(item for item in original.splitlines() if item.startswith("description:"))
        for length, valid in ((250, True), (251, False)):
            with self.subTest(length=length):
                path.write_text(original.replace(line, f'description: "{"y" * length}"'), encoding="utf-8")
                findings = self.errors_for("catalog")
                self.assertEqual(valid, not any("description must be 1-250" in item.message for item in findings))

    def test_skill_md_cap_rejects_61_lines(self) -> None:
        name = SKILL_NAMES[0]
        self.write(f"skills/{name}/SKILL.md", skill_text(name, 61))

        self.assertIn(f"skills/{name}/SKILL.md", self.cap_paths())

    def test_skill_md_cap_rejects_wide_file_under_line_cap(self) -> None:
        name = SKILL_NAMES[0]
        self.write(f"skills/{name}/SKILL.md", skill_text(name, 30, width=200))

        self.assertIn(f"skills/{name}/SKILL.md", self.cap_paths())

    def test_skill_md_at_cap_passes(self) -> None:
        name = SKILL_NAMES[0]
        text = skill_text(name, 60)
        self.write(f"skills/{name}/SKILL.md", text)

        self.assertEqual(60, len(text.splitlines()))
        self.assertEqual([], validator.validate(self.root))

    def test_contract_skills_get_the_wider_cap(self) -> None:
        self.add_catalog_skill("delivery-loop")
        path = "skills/delivery-loop/SKILL.md"
        self.write(path, skill_text("delivery-loop", 80, width=40))
        self.assertNotIn(path, self.cap_paths())

        self.write(path, skill_text("delivery-loop", 81))
        self.assertIn(path, self.cap_paths())
        self.assertEqual({"delivery-loop", "fast-pr-workflow"}, set(validator.CONTRACT_SKILLS))

    def test_markdown_caps_by_file_type(self) -> None:
        cases = (
            (f"skills/{SKILL_NAMES[0]}/references/guide.md", 80),
            ("agents/helper.md", 20),
            ("templates/output-styles/plain.md", 20),
            ("README.md", 80),
            ("policies/sample.md", 80),
        )
        for relative, cap in cases:
            with self.subTest(path=relative):
                self.write(relative, numbered_lines(cap))
                self.assertNotIn(relative, self.cap_paths())
                self.write(relative, numbered_lines(cap + 1))
                self.assertIn(relative, self.cap_paths())

    def test_global_rule_templates_are_capped_at_40_lines(self) -> None:
        for relative in ("templates/CLAUDE.md", "templates/AGENTS.md"):
            self.write(relative, numbered_lines(41))

        self.assertTrue({"templates/CLAUDE.md", "templates/AGENTS.md"} <= self.cap_paths())

    def test_reference_byte_cap_is_enforced(self) -> None:
        relative = f"skills/{SKILL_NAMES[0]}/references/guide.md"
        self.write(relative, numbered_lines(40, width=200))

        self.assertIn(relative, self.cap_paths())

    def test_references_must_be_one_level_deep(self) -> None:
        self.write(f"skills/{SKILL_NAMES[0]}/references/nested/deep.md", "short\n")

        findings = self.errors_for("caps")
        self.assertTrue(any("one level deep" in item.message for item in findings))

    def test_md_cap_rows_report_the_cap_table(self) -> None:
        self.write(f"skills/{SKILL_NAMES[0]}/SKILL.md", skill_text(SKILL_NAMES[0], 61))
        entries = validator.repo_entries(self.root)
        rows = {row.path: row for row in validator.md_cap_rows(self.root, validator.regular_files(self.root, entries))}

        row = rows[f"skills/{SKILL_NAMES[0]}/SKILL.md"]
        self.assertEqual((61, 60, 5_000), (row.lines, row.max_lines, row.max_bytes))
        self.assertFalse(row.within)

    def test_agent_description_cap(self) -> None:
        for length, valid in ((250, True), (251, False)):
            with self.subTest(length=length):
                self.write_agent(f'description: "{"z" * length}"\n')
                findings = self.errors_for("catalog")
                self.assertEqual(valid, not any("agent description" in item.message for item in findings))

    def test_agent_preload_cap(self) -> None:
        three = "".join(f"  - {name}\n" for name in SKILL_NAMES[:3])
        four = "".join(f"  - {name}\n" for name in SKILL_NAMES[:4])
        inline_four = "[" + ", ".join(SKILL_NAMES[:4]) + "]"
        cases = (
            (f"skills:\n{three}", True),
            (f"skills:\n{four}", False),
            (f"skills: {inline_four}\n", False),
            (f"skills: [{SKILL_NAMES[0]}]\n", True),
        )
        for skills, valid in cases:
            with self.subTest(skills=skills):
                self.write_agent(f"description: Sample helper agent.\n{skills}")
                findings = self.errors_for("catalog")
                self.assertEqual(valid, not any("agent preloads" in item.message for item in findings))
                self.assertFalse(any("unknown catalog skills" in item.message for item in findings))

    def test_bare_bash_grant_is_rejected(self) -> None:
        name = SKILL_NAMES[0]
        cases = (
            ("allowed-tools: Bash\n", True),
            ("allowed-tools: Read, Bash(*)\n", True),
            ("allowed-tools:\n  - Read\n  - Bash\n", True),
            ("allowed-tools: Bash(git status:*), Bash(git diff:*) Read\n", False),
            ("allowed-tools: Bash(git log --oneline)\n", False),
            ("allowed-tools:\n  - Read # read only\n", False),
            *((form, True) for form in UNSCOPED_BASH_FORMS.values()),
        )
        for frontmatter, rejected in cases:
            with self.subTest(frontmatter=frontmatter):
                self.write(f"skills/{name}/SKILL.md", skill_text(name, 10, extra_frontmatter=frontmatter))
                self.assertEqual(rejected, bool(self.errors_for("permissions")))

    def test_dangling_skill_name_in_prose_is_reported(self) -> None:
        line = "See the `code-comments` skill for the full guidance.\n"
        self.write("templates/CLAUDE.md", line)
        self.write("templates/AGENTS.md", line)
        self.write("agents/helper.md", "---\nname: helper\ndescription: Helper.\n---\nAsk the `code-helper` agent.\n")

        findings = self.errors_for("names")
        self.assertEqual({"templates/CLAUDE.md", "templates/AGENTS.md", "agents/helper.md"}, {item.path for item in findings})
        self.assertTrue(any("'code-comments'" in item.message and "line 1" in item.message for item in findings))

    def test_single_word_and_retired_names_are_reported(self) -> None:
        line = (
            "Hand off to the `shipper` agent, then the `qa` agent, then the `e2e-qa` skill, then load `code-reuse`.\n"
            "Ask the `helper` agent; `automation` was retired.\n"
        )
        self.write(f"skills/{SKILL_NAMES[0]}/SKILL.md", skill_text(SKILL_NAMES[0], 8) + line)

        names = {item.message.split("'")[1] for item in self.errors_for("names")}

        self.assertEqual({"shipper", "qa", "e2e-qa", "code-reuse", "automation"}, names)

    def test_symlinked_capped_markdown_is_rejected(self) -> None:
        name = SKILL_NAMES[0]
        self.write("docs/see.md", skill_text(name, 65, extra_frontmatter="allowed-tools: Bash\n"))
        self.write(f"skills/{SKILL_NAMES[1]}/references/real.md", "# Real\n")
        self.write("docs/agent.md", "---\nname: helper\ndescription: Helper.\n---\n")
        links = {
            f"skills/{name}/SKILL.md": Path("../../docs/see.md"),
            f"skills/{SKILL_NAMES[1]}/references/linked.md": Path("real.md"),
            "agents/helper.md": Path("../docs/agent.md"),
        }
        for relative, target in links.items():
            path = self.root / relative
            path.unlink(missing_ok=True)
            path.symlink_to(target)

        caps = {item.path for item in self.errors_for("caps") if "regular file" in item.message}

        self.assertEqual(set(links), caps)

    def test_dangling_name_check_ignores_keys_paths_and_known_names(self) -> None:
        self.add_catalog_skill("delivery-loop")
        self.write("CONTRIBUTING.md", CONTRIBUTING_KEY_LINE + "\n")
        self.write(
            f"skills/{SKILL_NAMES[0]}/references/tracker.md",
            "the adapter at `~/.config/ai-skills/task-tracker` is called by the `delivery-loop` skill\n"
            "Load the `sample-skill-02`\nskill next.\n",
        )

        self.assertEqual([], validator.validate(self.root))

    def test_denylist_reports_path_and_line_without_the_term(self) -> None:
        term = "QuietHarbor"
        denylist = self.outside_file(f"# private terms\n\n{term}\n")
        self.write("notes.md", "first line\nmentions quietharbor here\n")
        self.write("quietharbor-plan.txt", "clean\n")

        findings = self.errors_for("denylist", denylist)

        self.assertEqual({"notes.md", "quietharbor-plan.txt"}, {item.path for item in findings})
        self.assertTrue(any("line 2" in item.message for item in findings))
        self.assertFalse(any(term.lower() in item.message.lower() for item in findings))

    def test_denylist_comments_and_blank_lines_are_ignored(self) -> None:
        denylist = self.outside_file("# sample\n\n   \n")
        self.write("notes.md", "a sample note\n")

        self.assertEqual([], self.errors_for("denylist", denylist))

    def test_denylist_inside_the_repository_is_refused(self) -> None:
        denylist = self.write("private-terms.txt", "QuietHarbor\n")

        findings = self.errors_for("denylist", denylist)

        self.assertTrue(any("outside the repository" in item.message for item in findings))

    def test_denylist_is_off_without_flag_or_variable(self) -> None:
        self.write("notes.md", "QuietHarbor\n")

        with patch.dict(os.environ, {validator.DENYLIST_ENV: ""}):
            self.assertEqual([], self.errors_for("denylist"))

    def test_denylist_environment_variable_feeds_main(self) -> None:
        denylist = self.outside_file("QuietHarbor\n")
        self.write("notes.md", "QuietHarbor\n")
        stdout = StringIO()

        with (
            patch.dict(os.environ, {validator.DENYLIST_ENV: str(denylist)}),
            redirect_stdout(stdout),
            redirect_stderr(StringIO()),
        ):
            result = validator.main(["--root", str(self.root)])

        self.assertEqual(1, result)
        self.assertIn("[denylist] notes.md", stdout.getvalue())
        self.assertNotIn("quietharbor", stdout.getvalue().lower())

    def test_extra_skill_checks(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        extras = Path(holder.name)

        def make(name: str, text: str) -> Path:
            path = extras / name
            path.mkdir(parents=True, exist_ok=True)
            (path / "SKILL.md").write_text(text, encoding="utf-8")
            return path

        valid = make("extra-one", skill_text("extra-one", 10))
        self.assertEqual([], validator.check_extra_skill(valid, set(SKILL_NAMES), [self.root]))

        linked = extras / "extra-link"
        linked.symlink_to(valid, target_is_directory=True)
        cases = {
            "name": (make("extra-two", skill_text("other-name", 10)), "frontmatter name"),
            "description": (
                make("extra-three", f'---\nname: extra-three\ndescription: "{"d" * 251}"\n---\n'),
                "description must be 1-250",
            ),
            "bash": (make("extra-four", skill_text("extra-four", 10, extra_frontmatter="allowed-tools: Bash\n")), "unscoped Bash"),
            "cap": (make("extra-five", skill_text("extra-five", 61)), "exceed the cap"),
            "reserved": (make(SKILL_NAMES[0], skill_text(SKILL_NAMES[0], 10)), "collides"),
            "symlink": (linked, "must not be a symlink"),
            "frontmatter": (make("extra-six", "no frontmatter\n"), "missing YAML frontmatter"),
            "inside": (self.root / "skills" / SKILL_NAMES[1], "inside a catalog root"),
            **{
                f"bash-{label}": (
                    make(f"extra-bash-{label}", skill_text(f"extra-bash-{label}", 10, extra_frontmatter=form)),
                    "allowed-tools",
                )
                for label, form in UNSCOPED_BASH_FORMS.items()
            },
        }
        for label, (path, expected) in cases.items():
            with self.subTest(case=label):
                problems = validator.check_extra_skill(path, set(SKILL_NAMES) - {SKILL_NAMES[1]}, [self.root])
                self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_extra_skill_symlinks_are_rejected_wherever_they_sit(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        secret = Path(outside.name) / "secret.txt"
        secret.write_text("outside\n", encoding="utf-8")

        def make(name: str) -> Path:
            path = Path(holder.name) / name
            path.mkdir()
            (path / "SKILL.md").write_text(skill_text(name, 10), encoding="utf-8")
            return path

        cases = {
            "node_modules": (make("esc-modules"), "node_modules", Path(outside.name)),
            ".venv": (make("esc-venv"), ".venv", Path(outside.name)),
            "nested": (make("esc-nested"), "big/node_modules/p", secret),
            "inside": (make("esc-inside"), "notes.md", Path("SKILL.md")),
        }
        for label, (skill, relative, target) in cases.items():
            link = skill / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            with self.subTest(case=label):
                problems = validator.check_extra_skill(skill, set(SKILL_NAMES), [self.root])
                self.assertTrue(any(f"{relative} is a symlink" in problem for problem in problems), problems)

        hidden = make("esc-hidden-markdown")
        (hidden / "node_modules").mkdir()
        (hidden / "node_modules" / "long.md").write_text("x\n" * 81, encoding="utf-8")
        problems = validator.check_extra_skill(hidden, set(SKILL_NAMES), [self.root])
        self.assertTrue(any("node_modules/long.md" in problem and "exceed the cap" in problem for problem in problems))

    def test_listing_label_names_what_was_measured(self) -> None:
        findings = validator.check_listing({"a": "x" * 3_000}, {"a"}, label="selected skills with extras")

        self.assertEqual(["selected skills with extras costs 3001 characters; maximum is 3000"], [item.message for item in findings])

    def test_repo_meets_md_caps(self) -> None:
        entries = validator.repo_entries(SOURCE_ROOT)
        rows = validator.md_cap_rows(SOURCE_ROOT, validator.regular_files(SOURCE_ROOT, entries))
        failing = [row for row in rows if not row.within]
        nested = [
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in entries
            if path.is_file() and validator.nested_reference(PurePosixPath(path.relative_to(SOURCE_ROOT).as_posix()))
        ]
        table = "\n".join(
            ["path | lines | bytes | cap"]
            + [f"{row.path} | {row.lines} | {row.size} | {row.max_lines} lines, {row.max_bytes or '-'} bytes" for row in failing]
            + [f"{path} | - | - | references one level deep" for path in nested]
        )

        self.assertTrue(rows)
        if failing or nested:
            self.fail("\n" + table)

    def test_external_symlink_is_reported(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "target.txt"
        target.write_text("outside\n", encoding="utf-8")
        (self.root / "escape").symlink_to(target)

        self.assertTrue(self.errors_for("symlink"))

    def test_non_ascii_dash_is_reported(self) -> None:
        self.write("bad-copy.md", "left" + chr(0x2014) + "right\n")

        self.assertTrue(self.errors_for("hyphens"))

    def test_absolute_home_paths_are_reported(self) -> None:
        posix_path = "/" + "home" + "/sample-user/private.txt"
        root_path = "/" + "root" + "/private.txt"
        windows_path = "C:" + "\\" + "Users" + "\\sample-user\\private.txt"
        self.write("privacy.txt", f"{posix_path}\n{root_path}\n{windows_path}\n")

        self.assertGreaterEqual(len(self.errors_for("privacy")), 3)

    def test_non_utf8_artifact_is_reported(self) -> None:
        path = self.root / "artifact.bin"
        path.write_bytes(bytes((0xFF, 0xFE, 0xFD)))

        findings = self.errors_for("privacy")
        self.assertTrue(any("non-UTF-8" in item.message for item in findings))

    def test_binary_control_character_is_reported(self) -> None:
        path = self.root / "artifact.dat"
        path.write_bytes(b"text\x00payload")

        findings = self.errors_for("privacy")
        self.assertTrue(any("binary control character" in item.message for item in findings))

    def test_secret_signature_is_reported_without_value(self) -> None:
        candidate = "ghp_" + ("A" * 36)
        self.write("secret.txt", candidate + "\n")

        findings = self.errors_for("secrets")
        self.assertTrue(findings)
        self.assertNotIn(candidate, "\n".join(item.message for item in findings))


if __name__ == "__main__":
    unittest.main()
