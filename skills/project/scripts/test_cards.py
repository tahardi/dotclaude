import copy
import unittest

from cards import card_map, describe, validate

SPEC = "- **R-F-1:** Logs an attack.\n- **R-SEC-1:** Key auth.\n- **R-OPS-1:** CI.\n- **R-F-2:** Meal photos.\n"

PLAN = """# Plan

## Global Constraints

No comments.

## Epic: Setup

### T-S1: Create Repo

**Goal:** Make the repo (R-OPS-1).

**Acceptance criteria:**

- Repo exists.

### T-S2: Server Skeleton

**Goal:** Server with key auth (R-SEC-1). Uses the repo from T-S1.

**Files:**

- Create: `cmd/app/main.go`, `internal/server/server.go`
- [ ] **Step 1: Health test.** Fails first.

**Acceptance criteria:**

- Tests pass.

### T-S3: Attack Store

**Goal:** Store attacks (R-F-1).

**Files:**

- Create: `internal/store/store.go`
- [ ] **Step 1: Store test.** Fails first.

**Acceptance criteria:**

- Tests pass.

### T-S4: Attack Endpoint

**Goal:** Endpoint.

**Files:**

- Modify: `internal/server/server.go`
- [ ] **Step 1: Endpoint test.** Fails first.

**Acceptance criteria:**

- Tests pass.
"""

MANIFEST = {
    "project": "HALO",
    "plan": "plan.md",
    "plan_ref": "vault plan",
    "spec": "spec.md",
    "repo": "halo",
    "pre_pr": "make pre-pr",
    "epics": [{"id": "S", "name": "Setup", "description": "Setup."}],
    "cards": [
        {"id": "T-S1", "epic": "S", "points": 2, "labels": ["needs-taylor"], "workflow": False},
        {"id": "T-S2", "epic": "S", "points": 3, "blocked_by": ["T-S1"]},
        {"id": "T-S3", "epic": "S", "points": 3, "blocked_by": ["T-S1"]},
        {"id": "T-S4", "epic": "S", "points": 2, "blocked_by": ["T-S1"]},
    ],
    "future": [{"title": "Meal Photos", "epic": "S", "description": "Later.", "requirements": ["R-F-2"]}],
    "sprint": {"goal": "Setup.", "cards": ["T-S1", "T-S2"]},
}


def with_change(change):
    m = copy.deepcopy(MANIFEST)
    change(m)
    return m


class TestValidate(unittest.TestCase):
    def test_validate(self):
        cases = [
            ("happy path - valid manifest", MANIFEST, PLAN, SPEC, None),
            ("error - bad points", with_change(lambda m: m["cards"][1].update(points=4)), PLAN, SPEC,
             "T-S2: points 4 not in 1, 2, 3, 5, 8"),
            ("error - unknown blocker", with_change(lambda m: m["cards"][1].update(blocked_by=["T-S9"])), PLAN, SPEC,
             "T-S2: blocker T-S9 is not a manifest card"),
            ("error - cycle", with_change(lambda m: m["cards"][0].update(blocked_by=["T-S2"])), PLAN, SPEC,
             "blocker cycle"),
            ("error - script label", with_change(lambda m: m["cards"][1].update(labels=["parallelizable"])), PLAN,
             SPEC, "T-S2: label parallelizable is set by the script"),
            ("error - sprint missing blocker", with_change(lambda m: m["sprint"].update(cards=["T-S2"])), PLAN, SPEC,
             "sprint card T-S2 is blocked by T-S1"),
            ("error - uncovered requirement", MANIFEST, PLAN, SPEC + "- **R-PRIV-1:** No logs.\n",
             "requirement R-PRIV-1 is in no card"),
            ("error - workflow card without files", MANIFEST, PLAN.replace("- Create: `internal/store/store.go`", ""),
             SPEC, "T-S3: plan section has no **Files:**"),
            ("error - orphan plan task", MANIFEST, PLAN + "\n### T-S5: Extra\n\n**Goal:** x\n", SPEC,
             "plan task T-S5 is not in the manifest"),
        ]
        for name, manifest, plan, spec, want in cases:
            with self.subTest(name):
                # given
                given = (manifest, plan, spec)

                # when
                got = validate(*given)

                # then
                if want is None:
                    self.assertEqual(got, [])
                else:
                    self.assertTrue(any(want in e for e in got), got)


class TestCardMap(unittest.TestCase):
    def test_card_map(self):
        # given
        manifest, plan = MANIFEST, PLAN

        # when
        rows = {r["id"]: r for r in card_map(manifest, plan)}

        # then
        self.assertEqual(rows["T-S1"]["labels"], ["needs-taylor"])
        self.assertNotIn("parallelizable", rows["T-S2"]["labels"])
        self.assertIn("parallelizable", rows["T-S3"]["labels"])
        self.assertNotIn("parallelizable", rows["T-S4"]["labels"])
        self.assertEqual([rows[c]["depth"] for c in ("T-S1", "T-S2")], [0, 1])


class TestDescribe(unittest.TestCase):
    def test_describe(self):
        # given
        rows = {r["id"]: r for r in card_map(MANIFEST, PLAN)}
        keys = {"T-S1": "HALO-11", "T-S2": "HALO-12", "T-S3": "HALO-13", "T-S4": "HALO-14"}

        # when
        workflow = describe(MANIFEST, PLAN, rows["T-S2"], keys)
        manual = describe(MANIFEST, PLAN, rows["T-S1"], keys)

        # then
        self.assertIn("**Blocked by:** HALO-11.", workflow)
        self.assertIn("worktree add ~/Documents/code/wts/halo-halo-12-server-skeleton -b halo-12-server-skeleton", workflow)
        self.assertIn("`[HALO-12] Server Skeleton`", workflow)
        self.assertIn("Uses the repo from HALO-11.", workflow)
        self.assertIn("### Global Constraints\n\nNo comments.", workflow)
        self.assertNotIn("**Workflow:**", manual)
        self.assertIn("**Blocked by:** none.", manual)

    def test_describe_card_repo(self):
        # given
        rows = {r["id"]: r for r in card_map(MANIFEST, PLAN)}
        keys = {"T-S1": "HALO-11", "T-S2": "HALO-12", "T-S3": "HALO-13", "T-S4": "HALO-14"}
        row = {**rows["T-S2"], "repo": "maple", "pre_pr": "npm run pre-pr", "setup": "Run `npm ci` first."}

        # when
        got = describe(MANIFEST, PLAN, row, keys)

        # then
        self.assertIn("git -C ~/Documents/code/maple fetch origin", got)
        self.assertIn("~/Documents/code/wts/maple-halo-12-server-skeleton", got)
        self.assertIn("`npm run pre-pr` from the worktree root", got)
        self.assertIn("Never commit to `main`. Run `npm ci` first.", got)


if __name__ == "__main__":
    unittest.main()
