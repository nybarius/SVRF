"""Behavioral controls for fresh native decisions on one original checked candidate."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fakes import Clock, FakeGate, FakeGitHub, FakeRepo
from svrf.train import Train


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class Store:
    def __init__(self, root):
        self.root = Path(root)

    def object_path(self, digest):
        return self.root / "objects" / digest[:2] / (digest + ".json")

    def add(self, value):
        raw = canonical(value)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.object_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path, digest, raw


class Receiver:
    def __init__(self, root, outcomes=("refuse", "pass"), mutation=None, after=None):
        self.profile = {"host_binary_sha256": "sha256:" + "a" * 64,
                        "project": "/native/pröject"}
        self.store = Store(root)
        self.calls = []
        self.outcomes = outcomes
        self.mutation = mutation
        self.after = after
        self.seen = []
        self.originals = []

    def envelope(self, operation, response, status="COMPLETED", http=200):
        return {"operation": operation, "consumed": [],
                "result": {"schema": "meton.bridge-return/1", "operation": operation,
                           "effect_class": "EXECUTE" if operation != "project/status" else "OBSERVE",
                           "status": status, "http_status": http, "retry": False,
                           "runtime": {"executable": {"path": "/native/host",
                                      "sha256": self.profile["host_binary_sha256"]}},
                           "response": response}}

    def __call__(self, source):
        prior_calls = self.calls
        self.calls = []
        self.seen.append(deepcopy(source))
        step = len(self.seen) - 1
        outcome = self.outcomes[min(step, len(self.outcomes) - 1)]
        if outcome in ("pass", "observe", "mismatch", "no_observation"):
            result = {"status": "OBSERVED", "action": "act_land", "source": deepcopy(source),
                      "meton": {"task": "original-method", "observation": "sha256:" + "b" * 64}}
            if outcome == "observe":
                result["action"] = "act_observe"
            elif outcome == "mismatch":
                result["source"]["head"] = "another-head"
            elif outcome == "no_observation":
                del result["meton"]["observation"]
            if self.after:
                self.after(self, step, source)
            return result
        if outcome == "bare":
            raise ValueError("REVISION_CONFLICT")
        self.calls = [
            self.envelope("project/status", {"root": self.profile["project"], "effect_unknown": False}),
            self.envelope("file", {"result": {"revision": "fresh"},
                                  "organism_publication": {"status": "UNOBSERVED",
                                                          "read_failure": "PRIORITY_OFFER_UNOBSERVED"}}),
            self.envelope("project/evaluate-nymic", {"error": "REVISION_CONFLICT"},
                          status="REFUSED", http=409),
        ]
        if outcome == "stale_list":
            prior_calls[:] = self.calls
            self.calls = prior_calls
        if self.mutation:
            self.mutation(self)
        packet = {"schema": "institutional.train-meton-acting-receipt/1",
                  "status": "UNOBSERVED", "source": deepcopy(source), "profile": deepcopy(self.profile),
                  "read_failure": "REVISION_CONFLICT", "calls": deepcopy(self.calls)}
        if outcome == "stale_source":
            packet["source"]["head"] = "another-head"
        if outcome == "profile_mismatch":
            packet["profile"]["project"] = "/another/project"
        if outcome != "missing":
            path, digest, raw = self.store.add(packet)
            self.originals.append({"path": path, "sha256": digest, "raw": raw, "source": deepcopy(source)})
            if outcome == "corrupt":
                path.write_bytes(raw + b" ")
        if self.after:
            self.after(self, step, source)
        raise ValueError("REVISION_CONFLICT")


class RevisionContinuation(unittest.TestCase):
    def make(self, outcomes=("refuse", "pass"), mutation=None, after=None, rounds=1):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = FakeRepo([11, 12])
        gh, gate, clock = FakeGitHub(repo), FakeGate(repo), Clock()
        stopped = {"value": False}
        train = Train(repo, gh, gate, receipts=root / "receipts",
                      clock=clock, sleep=clock.sleep, poll_seconds=0,
                      max_rounds=rounds, family_size=1, comment=False,
                      pr_comments=False, status_checks=False,
                      stop_requested=lambda: stopped["value"])
        receiver = Receiver(root / "custody", outcomes, mutation=mutation, after=after)
        train.landing_decision = receiver
        return SimpleNamespace(train=train, receiver=receiver, repo=repo, gh=gh,
                               gate=gate, stopped=stopped, root=root)

    def assert_no_effects(self, case):
        self.assertEqual(case.repo.pushes, [])
        self.assertEqual(case.gh.merged, [])

    def test_fresh_decision_reuses_one_original_gate(self):
        case = self.make(rounds=2)
        receipt = case.train.run([11])
        self.assertEqual(case.gh.merged, [11])
        self.assertEqual(len(case.repo.pushes), 1)
        self.assertEqual(len(case.receiver.seen), 2)
        self.assertEqual(len(case.gate.trees), 1, "a native revision refusal reopened an unchanged gate")
        self.assertEqual(len(receipt["gates"]), 1)
        first, second = case.receiver.seen
        for key in ("pr", "head", "base", "prepared", "tree", "family", "family_tree", "gate_index", "gate"):
            self.assertEqual(first[key], second[key], key)
        self.assertNotEqual(first["receipt"], second["receipt"])
        self.assertEqual(len(receipt["decision_refusals"]), 1)
        refusal = receipt["decision_refusals"][0]
        original = case.receiver.originals[0]
        self.assertEqual(refusal["source"], first)
        self.assertEqual(refusal["original"], {"path": str(original["path"]),
                                             "sha256": "sha256:" + original["sha256"]})
        self.assertEqual(original["path"].read_bytes(), original["raw"])
        self.assertEqual(hashlib.sha256(original["raw"]).hexdigest(), original["sha256"])
        self.assertEqual(json.loads(original["raw"])["calls"][1]["result"]["response"]
                         ["organism_publication"]["status"], "UNOBSERVED")

    def test_missing_corrupt_or_stale_custody_never_continues(self):
        for outcome in ("bare", "missing", "corrupt", "stale_source", "profile_mismatch", "stale_list"):
            with self.subTest(outcome=outcome):
                case = self.make((outcome, "pass"))
                receipt = case.train.run([11])
                self.assertEqual(len(case.receiver.seen), 1)
                self.assert_no_effects(case)
                self.assertTrue(receipt["gates"][0]["green"])
                self.assertFalse(receipt.get("decision_refusals"))

    def test_unknown_or_different_native_boundaries_never_continue(self):
        mutations = {
            "bridge_unknown": lambda r: r.calls[0]["result"].update(status="UNKNOWN"),
            "bridge_read_failure": lambda r: r.calls[0]["result"].update(read_failure="LOST_RESPONSE"),
            "call_read_failure": lambda r: r.calls[0].update(read_failure="LOST_RESPONSE"),
            "primary_unknown": lambda r: r.calls[0]["result"]["response"].update(status="UNOBSERVED"),
            "primary_failure": lambda r: r.calls[1]["result"]["response"]["result"].update(read_failure="MISSING"),
            "primary_error": lambda r: r.calls[1]["result"]["response"]["result"].update(error="FAILED"),
            "effect_unknown": lambda r: r.calls[0]["result"]["response"].update(effect_unknown=True),
            "wrong_project": lambda r: r.calls[0]["result"]["response"].update(root="/other"),
            "final_unknown": lambda r: r.calls[-1]["result"].update(status="UNKNOWN"),
            "final_transport": lambda r: r.calls[-1].update(read_failure="OUTCOME_UNKNOWN"),
            "final_other_error": lambda r: r.calls[-1]["result"].update(response={"error": "OTHER_CONFLICT"}),
            "final_wrong_http": lambda r: r.calls[-1]["result"].update(http_status=503),
            "final_wrong_schema": lambda r: r.calls[-1]["result"].update(schema="other/1"),
            "final_wrong_operation": lambda r: r.calls[-1]["result"].update(operation="merge"),
            "final_wrong_runtime": lambda r: r.calls[-1]["result"]["runtime"]["executable"].update(sha256="sha256:" + "f"*64),
            "final_retry_true": lambda r: r.calls[-1]["result"].update(retry=True),
            "final_effect_unknown": lambda r: r.calls[-1]["result"].update(outcome_unknown=True),
        }
        for name, mutation in mutations.items():
            with self.subTest(boundary=name):
                case = self.make(mutation=mutation)
                receipt = case.train.run([11])
                self.assertEqual(len(case.receiver.seen), 1)
                self.assert_no_effects(case)
                self.assertTrue(receipt["gates"][0]["green"])
                self.assertFalse(receipt.get("decision_refusals"))

    def test_fresh_base_head_closed_or_held_state_stops_continuation(self):
        for kind in ("base", "head", "closed", "unobserved_state", "held", "stopped"):
            with self.subTest(change=kind):
                case = self.make()
                def changed(receiver, step, source):
                    if step:
                        return
                    if kind == "base":
                        case.repo.main = case.repo._new({0, 77}, ("c0",))
                    elif kind == "head":
                        case.repo.branches["pr-11"] = "changed-head"
                    elif kind == "closed":
                        pull = case.gh.pull
                        case.gh.pull = lambda n: {**pull(n), "state": "closed"}
                    elif kind == "unobserved_state":
                        pull = case.gh.pull
                        case.gh.pull = lambda n: {k: v for k, v in pull(n).items() if k != "state"}
                    elif kind == "held":
                        case.gh.labels = {11: ["train:hold"]}
                    else:
                        case.stopped["value"] = True
                case.receiver.after = changed
                receipt = case.train.run([11])
                self.assertEqual(len(case.receiver.seen), 1)
                self.assert_no_effects(case)
                self.assertEqual(len(receipt["decision_refusals"]), 1)

    def test_closed_during_fresh_decision_prevents_publication(self):
        case = self.make()
        def close_after_decision(receiver, step, source):
            if step != 1:
                return
            pull = case.gh.pull
            case.gh.pull = lambda n: {**pull(n), "state": "closed"}
        case.receiver.after = close_after_decision
        case.train.run([11])
        self.assertEqual(len(case.receiver.seen), 2)
        self.assertEqual(len(case.gate.trees), 1)
        self.assert_no_effects(case)

    def test_stop_during_fresh_pull_prevents_the_second_callback(self):
        case = self.make()
        def stop_on_pull(receiver, step, source):
            if step:
                return
            pull = case.gh.pull
            def stopped_pull(n):
                result = pull(n)
                case.stopped["value"] = True
                return result
            case.gh.pull = stopped_pull
        case.receiver.after = stop_on_pull
        case.train.run([11])
        self.assertEqual(len(case.receiver.seen), 1)
        self.assert_no_effects(case)

    def test_stop_during_post_decision_pull_prevents_publication(self):
        case = self.make()
        def stop_on_pull(receiver, step, source):
            if step != 1:
                return
            pull = case.gh.pull
            def stopped_pull(n):
                result = pull(n)
                case.stopped["value"] = True
                return result
            case.gh.pull = stopped_pull
        case.receiver.after = stop_on_pull
        case.train.run([11])
        self.assertEqual(len(case.receiver.seen), 2)
        self.assert_no_effects(case)

    def test_repeated_original_refusals_are_bounded_and_preserved(self):
        case = self.make(("refuse",))
        receipt = case.train.run([11])
        self.assertEqual(len(case.receiver.seen), 2)
        self.assertEqual(len(case.gate.trees), 1)
        self.assert_no_effects(case)
        self.assertEqual(len(receipt["decision_refusals"]), 2)
        for refusal, original in zip(receipt["decision_refusals"], case.receiver.originals):
            self.assertEqual(refusal["original"]["sha256"], "sha256:" + original["sha256"])
            self.assertEqual(original["path"].read_bytes(), original["raw"])
        self.assertTrue(any(x["reason"] == "METON_DECISION_REVISION_CONFLICT"
                            for x in receipt["retry_later"]))

    def test_fresh_nonlanding_or_invalid_evidence_still_refuses(self):
        for outcome in ("observe", "mismatch", "no_observation"):
            with self.subTest(outcome=outcome):
                case = self.make(("refuse", outcome))
                receipt = case.train.run([11])
                self.assertEqual(len(case.receiver.seen), 2)
                self.assertEqual(len(case.gate.trees), 1)
                self.assert_no_effects(case)
                self.assertEqual(len(receipt["decision_refusals"]), 1)

    def test_unchanged_real_f1_refusal_qualifies_without_erasing_secondary_failures(self):
        path = Path(os.environ.get("ORIGINAL_F1", str(Path(__file__).parent / "fixtures/meton_revision_refusal.json")))
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "6c3c2760c61a36ddc1e4b219ff61c4d8489cdcbb7a0b9ad7fbb1ac7451793df7")
        original = json.loads(raw)
        case = self.make()
        receiver = SimpleNamespace(profile=deepcopy(original["profile"]),
                                   calls=deepcopy(original["calls"]),
                                   store=Store(case.root / "real-original"))
        stored_path, digest, stored_raw = receiver.store.add(original)
        self.assertEqual(stored_raw, raw)
        accepted = case.train._retained_landing_revision_refusal(
            receiver, original["source"], [], ValueError("REVISION_CONFLICT"))
        self.assertEqual(accepted, {"path": str(stored_path), "sha256": "sha256:" + digest})
        self.assertEqual(stored_path.read_bytes(), raw)
        secondary = [c["result"]["response"]["organism_publication"]
                     for c in original["calls"]
                     if "organism_publication" in c.get("result", {}).get("response", {})]
        self.assertEqual(len(secondary), 4)
        self.assertTrue(all(x["status"] == "UNOBSERVED" for x in secondary))

    def test_multistep_family_retains_its_distinct_prefix_tree(self):
        case = self.make()
        case.train.family_size = 2
        receipt = case.train.run([11, 12])
        self.assertEqual(case.gh.merged, [11, 12])
        self.assertEqual(len(case.gate.trees), 1)
        self.assertEqual(len(case.receiver.seen), 3)
        first, fresh = case.receiver.seen[:2]
        self.assertNotEqual(first["tree"], first["family_tree"])
        self.assertEqual(first["prepared"], fresh["prepared"])
        self.assertEqual(first["gate"], fresh["gate"])
        self.assertEqual(len(receipt["decision_refusals"]), 1)
