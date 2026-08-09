"""Per-node backends: which system runs an agent node, and where its payload goes.

No single agent system reaches every model, and they bill to different meters, so
the backend is a property of the node rather than of the run. Everything else --
routing, retry ceilings, payloads, the budget -- is identical whichever backend a
node uses, and the tests that matter most here are the ones proving a backend
cannot quietly weaken a guarantee the driver already makes.
"""

import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from helpers import EXAMPLE_SPEC, SCRIPTS, tmpdir, valid_spec, write_spec

import render_workflow  # noqa: E402  (helpers puts SCRIPTS on the path)


def run_script(name, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def make_cli_stub(directory, name, body):
    """A fake backend CLI that records argv and stdin, then behaves like the real one.

    Python rather than a shell script for the reason `make_stub_claude` gives:
    Windows cannot execute an extensionless shebang script, and an unlaunchable
    stub falls through to PATH -- which on this machine means a real CLI spending
    real tokens from inside the test suite.

    Returns the WORKFLOW_*_CLI value that routes the runner here.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"{name}_stub.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "here = Path(__file__).resolve().parent\n"
        "argv = sys.argv[1:]\n"
        "stdin = sys.stdin.read()\n"
        '(here / "argv.json").write_text(json.dumps(argv), encoding="utf-8")\n'
        '(here / "stdin.txt").write_text(stdin, encoding="utf-8")\n'
        + body,
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{script}"'.replace(os.sep, "/")


CODEX_STUB = (
    # The real CLI writes its final message to the path after
    # --output-last-message and streams JSONL events to stdout.
    'out = argv[argv.index("--output-last-message") + 1]\n'
    'Path(out).write_text("codex says hello", encoding="utf-8")\n'
    'print(json.dumps({"type": "thread.started", '
    '"thread_id": "codex-sess-1"}))\n'
)

AGY_STUB = (
    'print(json.dumps({"conversation_id": "agy-conv-1", "status": "SUCCESS",\n'
    '                  "response": "agy says hello", "num_turns": 1}))\n'
)


def agent_spec(**node_fields):
    """valid_spec()'s agent node, carrying whatever backend fields a test needs."""
    spec = valid_spec()
    spec["nodes"][0].update(node_fields)
    return spec


def problems_for(spec):
    return render_workflow.validate(spec)


def matching(problems, needle):
    return [p for p in problems if needle in p]


class BackendValidation(unittest.TestCase):
    def test_default_backend_needs_no_field(self):
        """Absent means Claude. Every spec written before backends existed is valid."""
        self.assertEqual(problems_for(valid_spec()), [])

    def test_each_known_backend_validates(self):
        for backend in ("claude", "codex", "agy"):
            with self.subTest(backend=backend):
                self.assertEqual(problems_for(agent_spec(backend=backend)), [])

    def test_unknown_backend_is_refused(self):
        problems = problems_for(agent_spec(backend="gpt4all"))
        self.assertTrue(matching(problems, "backend 'gpt4all'"), problems)

    def test_backend_on_a_non_agent_node_is_refused(self):
        spec = valid_spec()
        spec["nodes"][1]["backend"] = "codex"  # the code node
        self.assertTrue(matching(problems_for(spec), "Only agent nodes call a model"))

    def test_openai_compat_requires_an_endpoint(self):
        spec = agent_spec(backend="openai-compat")
        self.assertTrue(matching(problems_for(spec), "names no endpoint"))

    def test_endpoint_on_a_cli_backend_is_refused(self):
        """A CLI already knows where it points; an endpoint would imply otherwise."""
        spec = agent_spec(backend="codex", endpoint="http://localhost:11434")
        self.assertTrue(matching(problems_for(spec), "already knows where it points"))

    def test_endpoint_must_be_a_url(self):
        spec = agent_spec(backend="openai-compat", endpoint="localhost:11434")
        self.assertTrue(matching(problems_for(spec), "not a URL"))

    def test_a_self_hosted_node_must_be_checkable(self):
        """Its output is raw material. Something has to be able to send it back.

        Being the target of a fail edge is exactly that property, so the rule reuses
        it rather than inventing a second notion of "reviewed".
        """
        spec = agent_spec(backend="openai-compat", endpoint="http://localhost:11434")
        # Drop the check->make fail edge, leaving nothing able to reject it.
        spec["edges"] = [e for e in spec["edges"] if e.get("when") != "fail"]
        spec["nodes"][1] = {"id": "check", "label": "Check", "kind": "code",
                            "detail": "verify"}

        self.assertTrue(matching(problems_for(spec), "would ship unreviewed"))

    def test_a_checked_self_hosted_node_is_fine(self):
        spec = agent_spec(backend="openai-compat", endpoint="http://localhost:11434")
        self.assertEqual(problems_for(spec), [])


class EndpointLocality(unittest.TestCase):
    """The privacy property comes from the address, never from the word "local"."""

    def test_loopback_forms_are_local(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:1234",
                    "http://[::1]:8080"):
            with self.subTest(url=url):
                self.assertTrue(render_workflow.endpoint_is_local(url))

    def test_a_lan_address_is_not_local(self):
        self.assertFalse(render_workflow.endpoint_is_local("http://192.168.1.50:11434"))

    def test_a_hostname_that_merely_contains_localhost_is_not_local(self):
        self.assertFalse(
            render_workflow.endpoint_is_local("http://localhost.evil.example/v1"))


class DesignDocSaysWhereThePayloadGoes(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tmpdir())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def render(self, spec):
        path = write_spec(self.dir, spec)
        out = self.dir / "out"
        run_script("render_workflow.py", str(path), "--out", str(out))
        return next(out.glob("*-design.md")).read_text(encoding="utf-8")

    def test_a_remote_endpoint_is_called_out_as_leaving_the_machine(self):
        doc = self.render(agent_spec(backend="openai-compat",
                                     endpoint="http://192.168.1.50:11434"))
        self.assertIn("off this machine", doc)
        self.assertIn("192.168.1.50", doc)

    def test_a_loopback_endpoint_is_not(self):
        doc = self.render(agent_spec(backend="openai-compat",
                                     endpoint="http://localhost:11434"))
        self.assertIn("this machine", doc)
        self.assertNotIn("off this machine", doc)

    def test_the_default_backend_names_its_vendor(self):
        self.assertIn("Anthropic", self.render(valid_spec()))


class EchoHandler(BaseHTTPRequestHandler):
    """Answers in the Anthropic shape and records what it was sent."""

    received = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length))
        EchoHandler.received.append((self.path, body))
        if self.path.endswith("/v1/messages") and self.server.reject_anthropic:
            self.send_error(404)
            return
        reply = json.dumps({
            "content": [{"type": "text", "text": f"got {len(body['messages'][0]['content'])}"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


class RunnerBackends(unittest.TestCase):
    """Exercises the generated runner's dispatch directly.

    Imported from a real generated package rather than reimplemented here: the
    runner is emitted from a template, so testing anything else would be testing a
    copy of the code that ships.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tmpdir())
        pkg = cls.dir / "pkg"
        run_script("scaffold_workflow.py", str(EXAMPLE_SPEC), "--out", str(pkg))
        spec = importlib.util.spec_from_file_location("gen_runner", pkg / "runner.py")
        cls.runner = importlib.util.module_from_spec(spec)
        # Registered before execution because @dataclass resolves annotations
        # through sys.modules[cls.__module__], which is None for a module that is
        # still only half-imported.
        sys.modules[spec.name] = cls.runner
        cls.addClassCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(cls.runner)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def serve(self, reject_anthropic=False):
        EchoHandler.received = []
        server = HTTPServer(("127.0.0.1", 0), EchoHandler)
        server.reject_anthropic = reject_anthropic
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_openai_compat_calls_the_endpoint_and_returns_the_text(self):
        url = self.serve()
        result = self.runner.run_agent("hello there", backend="openai-compat",
                                       endpoint=url, model="m")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.output, "got 11")
        self.assertEqual(EchoHandler.received[0][0], "/v1/messages")

    def test_openai_compat_falls_back_to_the_openai_path(self):
        """404 on /v1/messages means the server speaks the other dialect, not that
        the call failed."""
        url = self.serve(reject_anthropic=True)
        self.runner.run_agent("hello", backend="openai-compat", endpoint=url)
        self.assertEqual([path for path, _ in EchoHandler.received],
                         ["/v1/messages", "/v1/chat/completions"])

    def test_an_unreachable_endpoint_does_not_charge_the_budget(self):
        """launched=False is what separates "no call happened" from "the call failed",
        and only the second should cost a budgeted agent call."""
        result = self.runner.run_agent("hi", backend="openai-compat",
                                       endpoint="http://127.0.0.1:9")
        self.assertFalse(result.ok)
        self.assertFalse(result.launched)

    def test_agy_refuses_an_oversized_prompt_rather_than_truncating(self):
        """Antigravity takes its prompt on the command line and ignores stdin, so a
        large prompt would be cut and answered as if whole."""
        oversized = "x" * (self.runner.AGY_PROMPT_LIMIT + 1)
        result = self.runner.run_agent(oversized, backend="agy", model="m")
        self.assertFalse(result.ok)
        self.assertFalse(result.launched)
        self.assertIn("truncated silently", result.output)

    def test_an_unknown_backend_fails_without_launching_anything(self):
        result = self.runner.run_agent("hi", backend="nope")
        self.assertFalse(result.ok)
        self.assertFalse(result.launched)

    def stub(self, attr, name, body):
        """Point one backend constant at a stub and return where it records itself.

        The runner reads these from the environment at import, and this module is
        imported once for the class, so the constant is patched directly rather
        than through os.environ -- which would set a variable nothing re-reads.
        """
        home = self.dir / f"{name}-{self.id().rsplit('.', 1)[-1]}"
        value = make_cli_stub(home, name, body)
        original = getattr(self.runner, attr)
        setattr(self.runner, attr, shlex.split(value))
        self.addCleanup(setattr, self.runner, attr, original)
        return home

    def argv_of(self, home):
        return json.loads((home / "argv.json").read_text(encoding="utf-8"))

    def stdin_of(self, home):
        return (home / "stdin.txt").read_text(encoding="utf-8")

    def test_codex_gets_the_prompt_on_stdin_and_a_read_only_sandbox(self):
        """Three facts established against the real CLI and invisible to every
        other test: `-` reads the prompt from stdin, the sandbox is not inherited,
        and the reply is read from the file rather than the event stream."""
        home = self.stub("CODEX_CLI", "codex", CODEX_STUB)
        run_dir = self.dir / "codex-run"

        result = self.runner.run_agent("summarise this", backend="codex",
                                       model="gpt-5-codex", node_id="work",
                                       run_dir=run_dir)

        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.output, "codex says hello")
        self.assertEqual(result.session_id, "codex-sess-1")

        argv = self.argv_of(home)
        self.assertEqual(argv[0], "exec")
        self.assertEqual(argv[-1], "-", "the prompt must come from stdin")
        self.assertEqual(self.stdin_of(home), "summarise this")
        self.assertEqual(argv[argv.index("-s") + 1], "read-only",
                         "codex would otherwise edit files without asking")
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("-m", argv)

    def test_codex_resume_puts_the_session_id_where_the_cli_expects_it(self):
        """`codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]` -- the id is
        positional, after the flags and before the prompt. Get the order wrong and
        the id is read as the prompt, which fails as a confusing success."""
        home = self.stub("CODEX_CLI", "codex", CODEX_STUB)

        self.runner.run_agent("try again", backend="codex", session_id="sess-abc",
                              node_id="work", run_dir=self.dir / "codex-resume")

        argv = self.argv_of(home)
        self.assertEqual(argv[:2], ["exec", "resume"])
        self.assertEqual(argv[-2:], ["sess-abc", "-"])

    def test_agy_gets_the_prompt_on_argv_because_it_ignores_stdin(self):
        home = self.stub("AGY_CLI", "agy", AGY_STUB)

        result = self.runner.run_agent("summarise this", backend="agy", model="gemini")

        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.output, "agy says hello")
        self.assertEqual(result.session_id, "agy-conv-1")

        argv = self.argv_of(home)
        self.assertEqual(argv[argv.index("-p") + 1], "summarise this")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(self.stdin_of(home), "",
                         "sending agy a prompt on stdin would be sending it nowhere")

    def test_agy_resumes_by_conversation_id(self):
        home = self.stub("AGY_CLI", "agy", AGY_STUB)

        self.runner.run_agent("again", backend="agy", session_id="agy-conv-1")

        argv = self.argv_of(home)
        self.assertEqual(argv[argv.index("--conversation") + 1], "agy-conv-1")

    def test_a_cli_path_that_cannot_start_fails_the_node_instead_of_the_run(self):
        """Every way a command fails to start, not just the absent one.

        `FileNotFoundError` is one member of the OSError family and not the most
        likely: the manual tells you to point WORKFLOW_AGY_CLI at
        `%LOCALAPPDATA%\\agy\\bin\\agy.exe` because Antigravity is not on PATH, so
        stopping a directory short is the ordinary mistake. That raised
        PermissionError, which escaped run_agent as a traceback -- taking the whole
        run down with no node_result, no fail edge, no run_end, and the state file
        left live so a dead run still looked resumable.
        """
        a_directory = self.dir / "not-a-binary"
        a_directory.mkdir(exist_ok=True)
        a_text_file = self.dir / "not-a-binary.txt"
        a_text_file.write_text("this is not a program", encoding="utf-8")

        wrong = {"a directory": str(a_directory),
                 "a non-executable file": str(a_text_file),
                 "an empty string": ""}
        for attr, backend in (("AGENT_CLI", "claude"), ("CODEX_CLI", "codex"),
                              ("AGY_CLI", "agy")):
            for description, path in wrong.items():
                with self.subTest(backend=backend, cli=description):
                    self.addCleanup(setattr, self.runner, attr,
                                    getattr(self.runner, attr))
                    setattr(self.runner, attr, [path])
                    result = self.runner.run_agent(
                        "hi", backend=backend, node_id="n",
                        run_dir=self.dir / "cli-start")
                    self.assertFalse(result.ok)
                    self.assertFalse(result.launched, "nothing ran, so nothing is owed")
                    self.assertIn("could not start", result.output)

    def test_an_unparseable_endpoint_fails_the_node_instead_of_the_run(self):
        """The validator refuses these at scaffold time, so this is defence in
        depth -- but _post_json exists to turn failure into a return value, and
        Request() raises ValueError before any handler it has can apply."""
        result = self.runner.run_agent("hi", backend="openai-compat",
                                       endpoint="nonsense")
        self.assertFalse(result.ok)
        self.assertIn("not a usable URL", result.output)

    def test_a_cli_backend_that_is_not_installed_does_not_charge_the_budget(self):
        """Same distinction the HTTP backend makes, and it has to hold for all of
        them or the budget means something different per node."""
        self.addCleanup(setattr, self.runner, "CODEX_CLI", self.runner.CODEX_CLI)
        self.runner.CODEX_CLI = ["definitely-not-a-real-binary"]

        result = self.runner.run_agent("hi", backend="codex", node_id="work",
                                       run_dir=self.dir / "missing")

        self.assertFalse(result.ok)
        self.assertFalse(result.launched)

    def test_delegate_mode_ignores_the_backend(self):
        """When a person is doing the agent nodes there is no CLI to pick."""
        run_dir = self.dir / "delegated"
        run_dir.mkdir(exist_ok=True)
        os_environ = self.runner.os.environ
        os_environ["WORKFLOW_DELEGATE"] = "1"
        self.addCleanup(os_environ.pop, "WORKFLOW_DELEGATE", None)

        with self.assertRaises(SystemExit) as raised, \
                contextlib.redirect_stdout(io.StringIO()):
            self.runner.run_agent("do the thing", backend="codex",
                                  node_id="work", run_dir=run_dir)

        self.assertEqual(raised.exception.code, self.runner.NEEDS_AGENT)
        self.assertTrue((run_dir / "work.prompt.md").is_file())


if __name__ == "__main__":
    unittest.main()
