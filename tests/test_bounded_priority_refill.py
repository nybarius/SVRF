"""A failed priority read does not idle unrelated capacity in a bounded tick."""
import threading

import pytest

from fakes import DaemonGitHub, DaemonRepo, FakeGate
from svrf.errors import ReadFailed
from test_daemon import daemon


class PriorityFailure:
    def __init__(self):
        self.release = threading.Event()
        self.failed = threading.Event()
        self.peer_started = threading.Event()
        self.last_ordinary = threading.Event()
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, head, base):
        with self.lock:
            self.calls.append(head)
        if head == "h1":
            assert self.peer_started.wait(10), "second owned read did not start"
            self.failed.set()
            raise ReadFailed("CANDIDATE_SOURCE_UNOBSERVED")
        if head == "h2":
            self.peer_started.set()
            assert self.release.wait(15), "original admission was not released"
        if head == "h4":
            self.last_ordinary.set()
        return {"verdict": "MERGEABLE", "residuals": []}


def make_owner(tmp_path, *, tick_seconds=60):
    repo = DaemonRepo([1, 2, 3, 4])
    gh, gate, admission = DaemonGitHub(repo), FakeGate(repo), PriorityFailure()
    owner = daemon(
        repo, gh, gate, admission, tmp_path, jobs=1, admission_jobs=2,
        admission_round_reads=2, tick_seconds=tick_seconds,
        admission_priority_command="printf '1\\n2\\n3\\n'",
    )
    return repo, gh, gate, admission, owner


def retire(owner, admission):
    owner.request_stop()
    admission.release.set()
    while owner.inflight:
        owner.tick(drain=True)
    owner.close()


def test_bounded_refill_keeps_failure_and_priority_without_idling_the_free_slot(tmp_path):
    repo, gh, gate, admission, owner = make_owner(tmp_path)
    out, errors = {}, []

    def tick():
        try:
            out.update(owner.tick())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=tick)
    thread.start()
    try:
        assert admission.last_ordinary.wait(10), "ordinary refill waited for the original slow read"
        assert not admission.release.is_set()
        # There is only one free worker while h2 remains live: declared h3 leads h4.
        assert admission.calls[2:] == ["h3", "h4"]
        assert admission.calls.count("h1") == 1
    finally:
        admission.release.set()
        thread.join(15)
        assert not thread.is_alive()
        retire(owner, admission)

    assert not errors
    assert out["retry_later"] == [1]
    assert out["reasons"]["1"] == "CANDIDATE_SOURCE_UNOBSERVED"
    assert "refill_stopped" not in out
    assert sorted(out["admitted"]) == [2, 3, 4]
    assert sorted(gh.merged) == [2, 3, 4]
    assert out["inflight"] == []
    assert gate.peak == 1


@pytest.mark.parametrize("barrier", ["rate", "snapshot", "source", "stop"])
def test_bounded_refill_preserves_global_read_and_stop_barriers(tmp_path, barrier):
    repo, gh, gate, admission, owner = make_owner(tmp_path, tick_seconds=0.2)
    observed = []
    if barrier == "rate":
        original = gh.rate_limit

        def rate_limit():
            if admission.failed.is_set():
                observed.append("rate")
                return {"core": {"remaining": 0, "reset": 1000}}
            return original()

        gh.rate_limit = rate_limit
    elif barrier == "snapshot":
        original = gh.snapshot

        def snapshot():
            if admission.failed.is_set():
                observed.append("snapshot")
                raise ReadFailed("SNAPSHOT_UNOBSERVED")
            return original()

        gh.snapshot = snapshot
    elif barrier == "source":
        original = repo.fetch

        def fetch(numbers):
            if admission.failed.is_set() and any(number > 2 for number in numbers):
                observed.append("source")
                raise ReadFailed("CURRENT_SOURCE_UNOBSERVED")
            return original(numbers)

        repo.fetch = fetch
    else:
        original = owner._discover

        def discover(*args, **kwargs):
            if kwargs.get("refill"):
                observed.append("stop")
                owner.request_stop()
            return original(*args, **kwargs)

        owner._discover = discover

    try:
        out = owner.tick()
        assert observed
        assert sorted(admission.calls) == ["h1", "h2"]
        assert out["retry_later"] == [1]
        assert out["reasons"]["1"] == "CANDIDATE_SOURCE_UNOBSERVED"
        assert gh.merged == []
        assert gate.trees == []
    finally:
        retire(owner, admission)
